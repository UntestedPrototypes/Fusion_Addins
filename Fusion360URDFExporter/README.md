# Fusion 360 URDF Exporter Add-In

A high-performance Autodesk Fusion 360 add-in that exports assemblies and nested sub-assemblies to ROS-standard URDF format with automated rigid group merging, type-based ordered joint naming, and support for sketch- and joint-origin-based joints.

---

## Key Features

1. **Assembly & Sub-Assembly Kinematics**:
   - Recursively walks the assembly tree to construct directed kinematic chains.
   - Detects grounded components and defaults them to `base_link`.
   - Uses `transform2` to accurately compute relative transformations for arbitrarily nested sub-assemblies.

2. **Rigid Group & Rigid Joint Merging**:
   - Components grouped by rigid groups (`adsk.fusion.RigidGroups`) or non-origin rigid joints are merged into a single URDF link at the highest level possible.
   - Child bodies, surface bodies, and sheet metal parts are aggregated into the parent link.
   - Transitive merges ($A \to B \to C \Rightarrow C$) are automatically resolved.

3. **Strict Two-Joint-Origins Rule & Rigid Joint Support**:
   - **Mated Joint Origins Required**: A joint is **only created if made between two Joint Origins** (`geometryOrOriginOne` and `geometryOrOriginTwo` are `JointOrigin` features). Joints defined via faces or edges are omitted.
   - **Rigid Joints Included as Fixed**: Rigid joints made between two Joint Origins create `<joint type="fixed">` elements in the URDF, preserving child components as independent links.
   - **Coordinate & Axis Alignment**: The Joint Origin's Z-axis defines the URDF motion axis (+Z), and the origin point defines the relative transform origin.

4. **Chain & Level Joint Naming (User-Selectable & Customizable)**:
   - Identifies kinematic chains originating from `base_link` and topological depth levels along each branch.
   - User-selectable presets and editable template pattern in the export dialog:
     - `{branch_name}_c{chain}_l{level}` (**Default**, e.g. `leg_1_c1_l1`, `leg_1_c1_l2`, `leg_2_c2_l1`)
     - `{type}_c{chain}_l{level}` (e.g. `revolute_c1_l1`, `revolute_c1_l2`)
     - `{type}_{chain}_{level}` (e.g. `revolute_1_1`, `revolute_1_2`)
     - `joint_c{chain}_l{level}` (e.g. `joint_c1_l1`, `joint_c1_l2`)
     - `{type}_chain{chain}_level{level}` (e.g. `revolute_chain1_level1`)
     - `{branch_name}_joint_{level}` (e.g. `leg_1_joint_1`)
     - `{branch_name}_{level}` (e.g. `leg_1_1`)
     - `{type}_{level}` [Legacy Sequential] (e.g. `revolute_1`, `revolute_1A`)
     - Custom Pattern with placeholders `{branch_name}`, `{chain}`, `{level}`, `{type}`.

5. **Separate Visual & Collision Meshes**:
   - Visual mesh exported in `meshes/visual/<link>.stl` at user-selected quality (**Low**, **Medium**, or **High**).
   - Collision mesh exported in `meshes/collision/<link>.stl` at **Low** quality for fast simulation collision detection.
   - Multi-body links are exported as a combined binary STL with vertex coordinates scaled directly to meters ($1\text{ unit} = 1\text{ m}$).

6. **High-Accuracy Inertial Calculations**:
   - Computes mass, center of mass, and 3D rotational inertia tensors using Fusion 360's `HighCalculationAccuracy`.
   - Uses the **Parallel Axis Theorem** to combine multi-body inertia tensors around the combined center of mass:
     $$I_{total} = \sum_i \left[ I_i + m_i \left( (\mathbf{d}_i \cdot \mathbf{d}_i)\mathbf{I}_{3\times 3} - \mathbf{d}_i \mathbf{d}_i^T \right) \right]$$

---

## Directory Structure

```
Fusion360URDFExporter/
├── Fusion360URDFExporter.manifest   # Fusion 360 add-in manifest
├── Fusion360URDFExporter.py         # Main add-in entry point (UI & lifecycle)
├── install_addon.ps1                # PowerShell install script
├── README.md                        # User guide and quick start
├── TECHNICAL_OVERVIEW.md            # Technical architecture & future roadmap
├── config/
│   ├── __init__.py
│   └── defaults.py                  # Default parameters, limits, and unit constants
├── core/
│   ├── __init__.py
│   ├── tree_walker.py               # Assembly hierarchy traversal
│   ├── rigid_resolver.py            # Rigid group & joint merging
│   ├── joint_analyzer.py            # Joint geometry & axis analysis
│   ├── kinematic_builder.py         # URDF tree construction & naming
│   ├── mesh_exporter.py             # Binary STL exporter
│   ├── inertial_calc.py             # Mass & inertia tensor aggregation
│   ├── urdf_writer.py               # Schema-compliant XML generator
│   └── transform_utils.py           # Matrix3D and RPY orientation utilities
├── resources/                       # UI button icons (16x16, 32x32, 64x64)
└── tests/                           # Unit and integration test suite
```

---

## Installation in Autodesk Fusion 360

### Option 1: Via Fusion 360 UI (Recommended)
1. Open **Autodesk Fusion 360**.
2. Go to **Utilities** tab $\to$ **Add-Ins** panel $\to$ **Scripts and Add-Ins** (shortcut: `Shift + S`).
3. Select the **Add-Ins** tab.
4. Click the green **`+` (Add)** button next to *My Add-Ins*.
5. Browse and select the folder:
   ```
   C:\Users\hanjo\.gemini\antigravity\scratch\Fusion360URDFExporter
   ```
6. Select **Fusion360URDFExporter** in the list and click **Run**.
7. *(Optional)* Check **Run on Startup** if you want it loaded automatically.

### Option 2: Copy to Add-Ins Folder
Copy the `Fusion360URDFExporter` directory into your Fusion 360 Add-Ins folder:
```
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion360URDFExporter
```

---

## Assembly & Modeling Guidelines

To ensure smooth and accurate URDF generation, follow these modeling conventions in Autodesk Fusion 360:

### 1. Assembly Structure with Sub-Assemblies
- **Base Link / Grounded Component**:
  - Ground your robot base occurrence or select it in the **Root Component** field of the export dialog. It will become the URDF `base_link`.
- **Top-Level Sub-Assemblies (Chains / Limbs)**:
  - Organize each kinematic branch or limb (e.g., `Leg_1`, `Leg_2`, `Arm_Left`, `Arm_Right`) as a top-level sub-assembly directly under the root component.
  - The exporter recognizes these top-level occurrences and automatically uses their name as `{branch_name}` for joint and link naming.
- **Nested Moving Links**:
  - Place movable components/occurrences (e.g. coxa, femur, tibia) within the sub-assembly or in the assembly tree and link them sequentially with kinematic joints.

### 2. Joint Origins Requirement & Motion Orientation
- **Mated Between TWO Joint Origins Required**:
  - A joint is **ONLY created in the URDF if it is made between two Joint Origins** (`JointOrigin` features on both components).
  - Joints defined using faces, edges, sketch points, or single joint origins are ignored by the exporter.
- **Rigid Joints are Included**:
  - A **Rigid Joint** (`RigidJointType`) made between **two Joint Origins** creates an explicit `<joint type="fixed">` in the URDF, preserving the child component as its own independent link.
- **CRITICAL: The Z-Axis is Always the Motion Axis**:
  - In ROS and URDF conventions, **joint motion always occurs along or around the local Z-axis**:
    - **Revolute / Continuous Joints**: Rotation occurs around the Joint Origin's **+Z axis**.
    - **Prismatic Joints**: Linear translation occurs along the Joint Origin's **+Z axis**.
    - **Fixed Joints**: The Joint Origin establishes the rigid orientation and position of the child link.
  - When placing or editing a Joint Origin in Fusion 360, use the orientation manipulators or flip options so that the **blue Z-axis arrow points in the intended positive direction of motion**.
- **Joint Origin Anchor**:
  - The origin point `(0, 0, 0)` of the Joint Origin defines the exact joint origin `xyz` offset in the URDF.

### 3. Rigid Groups vs Rigid Joints
- **Rigid Groups**:
  - Components and bodies grouped via Fusion 360 **Rigid Groups** (`adsk.fusion.RigidGroups`) are automatically merged into their parent link as a single combined rigid body.
  - Their visual and collision meshes are aggregated, and their mass, center of mass, and inertia tensors are computed via the parallel axis theorem.
- **Rigid Joints NOT Between Two Joint Origins**:
  - Any rigid joint connecting components without two Joint Origins is treated as a CAD rigid merge, absorbing the child component into the parent link without generating a URDF joint.

---

## Usage

1. Open your robot assembly in Fusion 360.
2. Ensure your joints and rigid groups are configured.
3. In the toolbar, click **Export URDF** (in the *Scripts and Add-Ins* panel under the *Solid* tab).
4. In the dialog:
   - **Robot Name**: Name of your robot (defaults to the root component name).
   - **Export Directory**: Displays the current destination folder.
   - **Browse in Explorer...**: Click the **Select Folder in Explorer...** button to visually pick your export directory without manual typing.
   - **Visual Mesh Quality**: Select `Low`, `Medium`, or `High`.
   - **Open folder in Explorer when done**: Checkbox to automatically open the generated files in Windows Explorer upon completion.
5. Click **OK**.
6. The exporter will generate:
   ```
   <Export Directory>/<RobotName>/
   ├── <RobotName>.urdf
   └── meshes/
       ├── visual/
       │   └── *.stl
       └── collision/
           └── *.stl
   ```

---

## Running Automated Tests

Run the test suite using Python:
```bash
python -m unittest discover -s tests -v
```
All 10 unit and integration tests validate naming conventions, rigid group merging, RPY matrix math, binary STL generation, and end-to-end XML generation.
