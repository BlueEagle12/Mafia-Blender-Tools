# Mafia 1 Importer for Blender

![Blender Version](https://img.shields.io/badge/Blender-4.0+-orange)
![Addon Status](https://img.shields.io/badge/Status-Active-brightgreen)
![License](https://img.shields.io/badge/License-Custom-lightgrey)

**Version:** 1.2  
**Authors:** Blue Eagle, Sev3n  

---

## Overview

This Blender add-on allows importing game assets from **Mafia: The City of Lost Heaven**, including:

- `.4DS` model files  
- `scene2.bin` and `cache.bin` world data files  

It reconstructs scenes with correct geometry, materials, transforms, and object parenting.

---

## Features

### `.4DS` Import
- Imports meshes with their corresponding materials

### `scene2.bin` / `cache.bin` Import
- Parses element positions, rotations, scales, and additional properties
- Automatically links to and imports `.4DS` meshes and lights
- Builds scene structure

---

## Installation

### Scene2 & Cache Importers

1. Download or clone this repository.  
2. In Blender: **Edit → Preferences → Add-ons → Install...**  
3. Select the following files:
   - `import_scene2.py`  
   - `import_cache.py`  
   - `import_mafia.py`  
   *(or select the ZIP archive if bundled)*  
4. Enable these add-ons:
   - Mafia Scene2 (.bin) Importer  
   - Mafia Cache (.bin) Importer  
   - Mafia Import Shared  
5. Under **Add-on Preferences → Mafia Import Shared**, set the **Mafia Root Folder** to the game's install directory (must include the `.4DS` assets).

### `.4DS` Importer

1. In Blender: **Edit → Preferences → Add-ons → Install...**  
2. Select `import_4ds.py` (or ZIP archive if bundled)  
3. Enable the **LS3D 4DS Importer**  

---

## Usage

### Import Order Note (IMPORTANT)

Always import files in this order for scene reconstruction to work correctly:

1. `scene.4DS`  
2. `cache.bin`  
3. `scene2.bin`  

Importing out of order may result in missing or unlinked objects.

### Importing `.4DS` Files

1. Go to **File → Import → 4DS Model File (.4ds)**  
2. Select your `scene.4DS` or other model file  
3. Meshes will appear in the scene

### Importing `scene2.bin` or `cache.bin`

1. Go to **File → Import → Mafia (.bin)**  
2. Select either `cache.bin` or `scene2.bin` as needed  
3. World geometry and scene layout will be reconstructed  

---

## API Access

To call the importer programmatically in a script:

```python
from import_scene2 import ImportScene2

ImportScene2(filepath="C:/Games/Mafia/scene2.bin")
```

---

## Troubleshooting

- **Meshes not appearing?**  
  Make sure the **Mafia Root Folder** points to the location of your `.4DS` files. The importer uses this path to locate and match assets.

---

## Credits

- `scene2.bin` and `cache.bin` parsing by **Blue Eagle**  
- `.4DS` model importing by **Sev3n**  
- Language model assistance by **Grok 3 (xAI)**  

> Note: The `.4DS` importer was partially assisted by AI. All implementation logic and validation were completed by a human developer.

---

## Todo

- Fix potential blender freeze / crash after importing large scenes

---

## License

Custom / TBD — Contact the authors for details.
