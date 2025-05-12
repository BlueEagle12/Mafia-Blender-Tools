# Mafia 1 Format Handler for Blender

![Blender Version](https://img.shields.io/badge/Blender-4.0+-orange)
![Addon Status](https://img.shields.io/badge/Status-Active-brightgreen)
![License](https://img.shields.io/badge/License-Custom-lightgrey)

**Version:** 1.3
**Authors:** Blue Eagle, Sev3n  

---

## Overview

This Blender add-on allows importing game assets from **Mafia: The City of Lost Heaven**, including:

- `.4DS` model files  
- `scene2.bin` and `cache.bin` world data files  

It reconstructs scenes with correct geometry, materials, transforms, and object parenting.

---

## Features

### `.4DS` Import / Export
- Imports / Exports 4DS elements

### `scene2.bin` / `cache.bin` Import
- Parses element positions, rotations, scales, and additional properties
- Automatically links to and imports `.4DS` meshes and lights
- Builds scene structure


---

## Installation

### Step-by-Step

1. **Download the Add-on**  
   - Visit the GitHub repository  
   - Click the green **“Code”** button  
   - Select **“Download ZIP”**

2. **Install in Blender**  
   - Open Blender  
   - Go to **Edit → Preferences → Add-ons → Install…**  
   - Select the ZIP file you just downloaded (do **not** extract it)

3. **Enable the Add-on**  
   - In the Add-ons tab, search for **Mafia**  
   - Enable **Mafia_Formats**

4. **Set Mafia Root Folder**  
   - Still in Preferences, expand the **Mafia_Formats** panel  
   - Set the **Mafia Root Folder** to your Mafia install directory (must have `.4DS` assets extracted into a models child folder)

---

## Usage

### Import Order Note (IMPORTANT)

Always import files in this order for scene reconstruction to work correctly:

1. `scene.4DS`  
2. `scene2.bin`  
3. `cache.bin`  

Importing out of order may result in missing or unlinked objects.

### Importing `.4DS` Files

1. Go to **File → Import → 4DS Model File (.4ds)**  
2. Select your `scene.4DS` or other model file  
3. Meshes will appear in the scene

### Exporting `.4DS` Files

#Todo

### Importing `scene2.bin` or `cache.bin`

1. Go to **File → Import → Mafia (.bin)**  
2. Select either `cache.bin` or `scene2.bin` as needed  
3. World geometry and scene layout will be reconstructed  

## Troubleshooting

- **Meshes not appearing?**  
  Make sure the **Mafia Root Folder** points to the parent location of your `.4DS` files. The importer uses this path to locate and match assets.

---

## Credits

- `scene2.bin` and `cache.bin` parsing by **Blue Eagle**
- `.4DS` model importer / exporter refactored and updated by **Blue Eagle**


- original `.4DS` model importer / exporter by **Sev3n** & **Grok 3 (xAI)**  
> Note: The original `.4DS` importer was partially assisted by AI. All implementation logic and validation were completed by a human developer.

---

## Todo

- Fix exporting
- Add .bin exporting

---
