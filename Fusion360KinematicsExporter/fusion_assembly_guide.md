# Fusion 360 to URDF: Assembly Best Practices

The Kinematics Exporter reads your Fusion 360 design by scanning for unique components and joints. Because of how Fusion 360 handles internal coordinate systems and shared memory for copied components, **instanced subassemblies (e.g., copying a "Leg" subassembly 4 times) will not export correctly out of the box.** 

To ensure your robot exports perfectly, follow these rules:

## 1. Make Copied Subassemblies "Independent"
If you design one leg and copy-paste it 3 times, Fusion treats them as the exact same object. Their internal components (e.g., `Thigh:1`) will have the exact same name across all 4 legs, and the exporter will accidentally merge them together.
* **The Fix**: Right-click your copied legs in the browser and select **"Make Independent"**. This forces Fusion to treat them as unique physical objects with unique names (e.g., `Thigh_2:1`).

## 2. Break External Links
If you imported your leg from a separate Fusion 360 file (indicated by a chain-link icon), the exporter cannot safely read its internal joint origins.
* **The Fix**: Right-click the imported assembly in the browser and select **"Break Link"**.

## 3. Keep Joints at the Root Level (Recommended)
While the exporter tries to find joints hidden deep inside subassemblies, Fusion's API struggles to calculate the true world-position of joints that are buried inside multiple instanced folders. 
* **The Fix**: For the most reliable export, define all of your **moving joints (Revolute, Prismatic)** in the main, top-level assembly. 

## 4. Let the Exporter Handle Rigid Parts
You do not need to combine all your static parts into a single solid body. 
* **The Fix**: Use **Rigid Joints** (or Rigid Groups) in Fusion 360 to lock static components together (e.g., a motor, a casing, and a frame). The exporter is smart enough to detect Rigid joints and will automatically merge those components into a single, seamless URDF Link for you.

---

### Ideal File Structure Example:

* 📦 **Quadruped_Robot (Top Level)**
  * 🔗 *Revolute Joint* (Base -> FL_Hip)
  * 🔗 *Revolute Joint* (FL_Hip -> FL_Thigh)
  * 🔗 *Revolute Joint* (Base -> FR_Hip)
  * 📁 **Base_Chassis** (Component)
    * ⚙️ Body1 (Frame)
    * ⚙️ Body2 (Lidar) - *Rigid jointed to Frame*
  * 📁 **FL_Hip_Independent** (Component)
  * 📁 **FL_Thigh_Independent** (Component)
  * 📁 **FR_Hip_Independent** (Component)
  * 📁 **FR_Thigh_Independent** (Component)
