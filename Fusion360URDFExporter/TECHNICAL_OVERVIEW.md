# Autodesk Fusion 360 URDF Exporter — Technical Overview & Future Development Roadmap

## 1. Executive Summary & Architecture Overview

The **Autodesk Fusion 360 URDF Exporter** is a modular, high-performance add-in developed to bridge CAD mechanical assemblies in Fusion 360 with modern robotics simulation and control frameworks (ROS, ROS 2, Gazebo, PyBullet, MuJoCo, Webots).

Unlike legacy export scripts (which suffered from C++ internal validation crashes on nested assemblies, lack of Joint Origin support, incorrect inertia transformations, or loss of multi-body components), this add-in is built from the ground up on a robust modular pipeline:

```
Assembly Tree (Fusion 360 Document)
   │
   ▼
[ tree_walker.py ] ─────── Scans component/occurrence hierarchy & collects BRep bodies
   │
   ▼
[ joint_analyzer.py ] ──── Filters joints made between TWO JointOrigins (Revolute, Prismatic, Rigid)
   │
   ▼
[ rigid_resolver.py ] ──── Merges RigidGroups and non-origin rigid joints (protects kinematic links)
   │
   ▼
[ kinematic_builder.py ] ── Builds kinematic tree, anchors base_link, applies chain/level naming
   │
   ├──────────────────────────────┬──────────────────────────────┐
   ▼                              ▼                              ▼
[ mesh_exporter.py ]     [ inertial_calc.py ]          [ urdf_writer.py ]
• Binary STL tessellation • Parallel Axis Theorem       • Schema-compliant XML
• Frame scaling to meters • Multi-body tensor sum       • Pretty-printed URDF
• Visual & Collision      • Link-frame relative         • Dynamics & Limits
   │                              │                              │
   └──────────────────────────────┴──────────────────────────────┘
                                  │
                                  ▼
                     Exported URDF Robot Package
                     ├── <robot_name>.urdf
                     └── meshes/
                         ├── visual/*.stl
                         └── collision/*.stl
```

---

## 2. Core Mathematical & Kinematic Pipeline

### 2.1 Coordinate Systems, Units, and Scaling
* **Fusion 360 Internal Units**: Fusion 360 internally evaluates lengths, matrix translations, and physical properties in **centimeters (cm)**, masses in **kilograms (kg)**, and moments of inertia in **$\text{kg}\cdot\text{cm}^2$**.
* **URDF / ROS Standard Units**: The URDF standard requires **meters (m)**, **kilograms (kg)**, **radians (rad)**, and moments of inertia in **$\text{kg}\cdot\text{m}^2$**.
* **Conversion Constants**:
  - Distance: $\text{meters} = \text{centimeters} \times 0.01$
  - Inertia: $\text{kg}\cdot\text{m}^2 = \text{kg}\cdot\text{cm}^2 \times 10^{-4}$

### 2.2 Matrix Transforms & Joint Origin Coordinate Frames
* **Occurrence World Transforms**:
  Extracted via `occurrence.transform2` (Matrix3D), converted to 16-element flat row-major lists:
  $$\mathbf{T} = \begin{bmatrix} r_{00} & r_{01} & r_{02} & t_x \\ r_{10} & r_{11} & r_{12} & t_y \\ r_{20} & r_{21} & r_{22} & t_z \\ 0 & 0 & 0 & 1 \end{bmatrix}$$
* **Orthonormal Joint Origin Construction**:
  When a joint origin is defined by origin $\mathbf{P}$, primary axis $\mathbf{Z}$ (motion axis), and secondary axis $\mathbf{X}'$:
  $$\mathbf{Z}_{unit} = \frac{\mathbf{Z}}{\|\mathbf{Z}\|}, \quad \mathbf{Y}_{unit} = \frac{\mathbf{Z}_{unit} \times \mathbf{X}'}{\|\mathbf{Z}_{unit} \times \mathbf{X}'\|}, \quad \mathbf{X}_{unit} = \mathbf{Y}_{unit} \times \mathbf{Z}_{unit}$$
* **Relative Joint Transform Propagation**:
  For parent link frame $\mathbf{T}_{parent}$ and joint world frame $\mathbf{T}_{joint}$:
  $$\mathbf{T}_{rel} = \mathbf{T}_{parent}^{-1} \times \mathbf{T}_{joint}$$
  The joint's URDF `<origin xyz="..." rpy="..." />` is directly extracted from $\mathbf{T}_{rel}$.

### 2.3 Roll-Pitch-Yaw (RPY) Decomposition & Singularity Handling
* Standard Tait-Bryan $Z$-$Y$-$X$ angles ($\text{yaw } \psi$, $\text{pitch } \theta$, $\text{roll } \phi$):
  $$\theta = -\arcsin(r_{20})$$
  $$\phi = \text{atan2}(r_{21}, r_{22}), \quad \psi = \text{atan2}(r_{10}, r_{00})$$
* **Gimbal Lock Protection**: When $\theta \approx \pm \pi/2$ ($r_{20} = \mp 1$):
  $$\theta = \pm \frac{\pi}{2}, \quad \phi = 0, \quad \psi = \text{atan2}(\mp r_{01}, r_{11})$$
  This formulation guarantees that the local Z-axis unit vector is preserved without erroneous axis flipping.

### 2.4 Multi-Body Inertia Aggregation via Parallel Axis Theorem
For links composed of multiple bodies (e.g. merged brackets, covers, motors), the aggregate mass $M$, center of mass $\mathbf{C}$, and rotational inertia tensor $\mathbf{I}_{total}$ relative to the link coordinate frame are computed as:
$$M = \sum_i m_i$$
$$\mathbf{C} = \frac{1}{M} \sum_i m_i \mathbf{c}_i$$
For each body $i$ with local inertia tensor $\mathbf{I}_i$ and translation vector $\mathbf{d}_i = \mathbf{c}_i - \mathbf{C}$:
$$\mathbf{I}_{total} = \sum_i \left[ \mathbf{I}_i + m_i \left( (\mathbf{d}_i \cdot \mathbf{d}_i)\mathbf{I}_{3\times 3} - \mathbf{d}_i \mathbf{d}_i^T \right) \right]$$

---

## 3. Kinematic Rules & Assembly Structure

### 3.1 Strict "Two Joint Origins Required" Rule
1. **Kinematic Joints**:
   - A joint in Fusion 360 is **ONLY created in the URDF if it is made between two Joint Origins** (`geometryOrOriginOne` is a `JointOrigin` AND `geometryOrOriginTwo` is a `JointOrigin`).
   - Joints created using faces, edges, sketch points, or as-built joints are omitted from the URDF kinematic tree.
2. **Motion Axis Convention**:
   - URDF specifies that motion occurs along or around the **local $+Z$ axis**.
   - Orient every Joint Origin in Fusion 360 so that its blue Z-axis arrow points along the desired positive motion direction.
3. **Rigid Joints vs. Rigid Groups**:
   - **Rigid Joints between two Joint Origins**: Exported as `<joint type="fixed">` in the URDF. The child link is preserved as an independent link in the kinematic tree.
   - **Rigid Groups**: Fusion 360 `RigidGroups` merge components into their parent link (combining meshes, mass, and inertia).
   - **Rigid Joints without two Joint Origins**: Treated as CAD assembly alignment; components are merged into parent link.

### 3.2 Chain and Level Joint Naming Convention
Joints are topologically analyzed along kinematic chains originating from `base_link`:
* **Default Pattern**: `{branch_name}_c{chain}_l{level}` (e.g. `leg_1_c1_l1`, `leg_1_c1_l2`, `leg_2_c2_l1`)
* **Available Placeholders**:
  - `{branch_name}`: Top-level sub-assembly name (e.g., `leg_1`, `arm_right`)
  - `{chain}`: 1-indexed kinematic chain counter
  - `{level}`: Topological depth along branch ($1, 2, 3\dots$)
  - `{type}`: Joint type (`revolute`, `prismatic`, `continuous`, `fixed`)
  - `{child_link}`: Name of moving child link
  - `{parent_link}`: Name of parent link

### 3.3 Fast Batch Mesh Tessellation & Collision Reuse
* **Single-Pass Leaf Occurrence Export**: BRep bodies are isolated and exported at their leaf occurrence level, preventing child subassemblies from bleeding into parent links.
* **Instant Collision Mesh Reuse**: Visual STL meshes are instantly duplicated for collision meshes, cutting CAD mesh tessellation time by 50%.
* **Skip Invisible Meshes (Enabled by Default)**: Allows rapid kinematic and joint frame validation in simulation without waiting for hundreds of complex CAD parts to tessellate.

---

## 4. History of Development & Implemented Milestones

### Phase 1: Foundation & Modular Architecture
- Created core add-in structure with `Fusion360URDFExporter.manifest` and `Fusion360URDFExporter.py`.
- Developed modular subsystems: `tree_walker`, `joint_analyzer`, `rigid_resolver`, `kinematic_builder`, `mesh_exporter`, `inertial_calc`, `urdf_writer`, `transform_utils`.
- Implemented unit and integration test framework mockable outside Fusion 360.

### Phase 2: Coordinate Transformations & Numerical Robustness
- Implemented orthonormal frame construction from Fusion 360 `JointOrigin` entities.
- Solved gimbal-lock singularity in Roll-Pitch-Yaw (RPY) decomposition when pitch $\approx -90^\circ$ (preventing unwanted Z-axis flips on wrist and leg joints).
- Resolved proxy context extraction for assembly components and subassemblies.

### Phase 3: Body Isolation & Subassembly Hierarchy Fixes
- Fixed occurrence body bleed where parent container components included bodies belonging to nested sub-assembly links.
- Implemented container occurrence promotion (promoting leaf parts to `base_link` when joints connect to inner base bodies).
- Transitive rigid merge resolution ($A \to B \to C \Rightarrow C$) with cycle detection.

### Phase 4: Performance & User Experience Enhancements
- Added real-time `ExportProgressDialog` with step-by-step progress tracking, link tessellation indicators, and responsive event flushing.
- Added native Windows Explorer folder picker button (`Browse...`).
- Added "Skip Invisible Meshes" option (default: `True`) for fast kinematic iterations.
- Added user-configurable Visual Mesh Quality (`Low`, `Medium`, `High`) and physical calculation accuracy options.

### Phase 5: Chain & Level Joint Naming System
- Added topological chain and level discovery algorithm.
- Provided UI dropdown presets and customizable naming template pattern in the export dialog.
- Added bracket typo auto-normalization (`[chain]`, `{chain)`, `(chain)` $\to$ `{chain}`).

### Phase 6: Assembly Guidelines & Strict Joint Origins Constraint
- Added collapsible "Assembly & Modeling Guidelines (Help)" section inside the Fusion 360 command dialog.
- Enforced strict requirement: **only create joints made between two Joint Origins**.
- Integrated **Rigid Joints made between two Joint Origins as URDF `<joint type="fixed">`**, keeping child links separate.
- Updated documentation across `README.md` and walkthrough artifacts.

### Phase 7: Comprehensive Test Suite
- Built test suite with 48 automated test cases covering naming conventions, rigid merging, matrix math, binary STL generation, body isolation, visibility toggles, two-joint-origins filtering, and XML compliance.

---

## 5. Development Goals & Future Roadmap

For future development and extensions, the following features are planned:

### 1. ROS 2 / Colcon Package Generator (Priority: High)
- **Objective**: In addition to exporting `<robot>.urdf` and meshes, automatically generate a complete ROS 2 package structure:
  ```
  <robot_name>_description/
  ├── CMakeLists.txt
  ├── package.xml
  ├── urdf/
  │   ├── <robot_name>.urdf
  │   └── <robot_name>.urdf.xacro
  ├── meshes/
  │   ├── visual/
  │   └── collision/
  ├── launch/
  │   ├── display.launch.py       (Loads RViz2 and joint_state_publisher_gui)
  │   └── gazebo.launch.py        (Spawns robot in Gazebo Sim)
  └── rviz/
      └── default.rviz
  ```

### 2. Geometric Primitives for Collision Models (Priority: High)
- **Objective**: Instead of exporting dense STL meshes for collision geometry, automatically detect primitive shapes:
  - Cylinders (bearings, shafts, motor cans) $\to$ `<cylinder radius="..." length="..." />`
  - Boxes (batteries, electronic enclosures, plates) $\to$ `<box size="..." />`
  - Spheres $\to$ `<sphere radius="..." />`
- **Benefit**: Vastly improves physics engine performance and stability in Gazebo, MuJoCo, and Isaac Sim.

### 3. Material, Color & Texture Mapping (Priority: Medium)
- **Objective**: Extract RGB color and transparency from Fusion 360 appearances/materials:
  ```xml
  <material name="dark_aluminum">
    <color rgba="0.2 0.2 0.2 1.0" />
  </material>
  ```
- **Fallback**: Generate distinct colors per link if no appearance is assigned.

### 4. Hardware Interface & Transmission Tags for ros2_control (Priority: Medium)
- **Objective**: Automatically append `<transmission>` and `<ros2_control>` tags:
  ```xml
  <ros2_control name="GazeboSystem" type="system">
    <hardware>
      <plugin>gazebo_ros2_control/GazeboSystem</plugin>
    </hardware>
    <joint name="leg_1_c1_l1">
      <command_interface name="position"/>
      <state_interface name="position"/>
      <state_interface name="velocity"/>
    </joint>
  </ros2_control>
  ```

### 5. Mimic Joints & Closed Kinematic Chains (Priority: Medium)
- **Objective**: Detect closed loops (e.g. four-bar linkages, delta robots, parallel grippers) and annotate passive joints with `<mimic joint="..." multiplier="..." offset="..." />` or SDF/URDF loop tags.

### 6. Interactive 3D Kinematic Preview in Dialog (Priority: Low)
- **Objective**: Display an interactive 3D canvas or tree visualization inside the Fusion 360 palette before exporting, showing kinematic chains, detected branches, and joint names.

---

## 6. Directory Structure & Key Files

```
Fusion360URDFExporter/
├── Fusion360URDFExporter.manifest   # Fusion 360 Add-In Manifest
├── Fusion360URDFExporter.py         # Entry point: UI commands, dialog handlers, execution
├── install_addon.ps1                # One-click Windows PowerShell installer
├── README.md                        # User guide and quick start documentation
├── TECHNICAL_OVERVIEW.md            # Comprehensive architecture & development roadmap (this file)
├── config/
│   ├── __init__.py
│   └── defaults.py                  # Default limits, tolerance constants, naming presets
├── core/
│   ├── __init__.py
│   ├── tree_walker.py               # Assembly hierarchy traversal & body discovery
│   ├── rigid_resolver.py            # Rigid group & non-origin rigid joint merging
│   ├── joint_analyzer.py            # Two-JointOrigins filter, axis & limit extraction
│   ├── kinematic_builder.py         # URDF tree construction & topological naming
│   ├── mesh_exporter.py             # Binary STL tessellation & link frame alignment
│   ├── inertial_calc.py             # Parallel Axis Theorem & inertia aggregation
│   ├── urdf_writer.py               # XML formatting and URDF validation
│   ├── transform_utils.py           # Matrix3D, RPY decomposition, coordinate math
│   └── diagnostics.py               # Assembly diagnostics reporting tool
├── resources/
│   ├── 16x16.png                    # Command toolbar button icons
│   ├── 32x32.png
│   └── 64x64.png
└── tests/
    ├── test_body_isolation_and_mesh_export.py
    ├── test_end_to_end_pipeline.py
    ├── test_inertial_and_stl.py
    ├── test_joint_origins_and_frames.py
    ├── test_naming_convention.py
    ├── test_rigid_resolver.py
    ├── test_two_joint_origins_rule.py
    └── test_urdf_writer.py
```

---

## 7. Running Unit Tests

To run the automated test suite locally:
```bash
python -m unittest discover -s tests -v
```
All **48 unit tests** should pass with `OK`.
