# Mafia 1 `.4DS` & `scene2.bin` Importer for Blender

**Version:** 1.0  
**Blender:** 4.0+  
**Author:** Blue Eagle **Sev3n** & **Grok 3 (xAI)**  

---

## Overview

This Blender add-on lets you import:

- **`.4DS` models** from Mafia 1  
- **`scene2.bin`** world files  


---

## Features

- **Import `.4DS` meshes** with materials and textures  
- **Parse `scene2.bin`** to recreate positions, rotations, scales  
- **Automatic dummy parenting**: each mesh gets an Empty named `<object_name>_root` with correct transform  
- **Progress reporting** and responsive UI (via Blender’s progress bar)  (TODO)

---

## Installation

1. Download or clone this repository.  
2. In Blender, go to **Edit → Preferences → Add-ons → Install…**  
3. Select the `import_scene2.py` file (or the ZIP archive).  
4. Enable **“Mafia Scene2 (.bin) Importer”**.  
5. (Optional) Under **Add-on Preferences**, set **Mafia Root Folder** to your game install folder for faster mesh lookup.

## Usage

1. **File → Import → Mafia Scene2 (.bin)**  
2. Navigate to your `scene2.bin` and click **Import**.  
3. Imported meshes will appear parented under Empties named `<object_name>_root`.

---

## Installation (4DS Importer)

1. Download or clone this repository.  
2. In Blender, go to **Edit → Preferences → Add-ons → Install…**  
3. Select the `import_4ds.py` file (or the ZIP archive).  
4. Enable **“LS3D 4DS Importer”**.  

## Usage

1. **File → Import → 4DS Model File (.4ds)**  
2. Navigate to your `.4ds` and click **Import**.  
3. Imported meshes will appear under their interal names.

---

## API / Scripting

If you want to hook into the importer programmatically:

```python
  ImportScene2(filepath="C:\path\to\scene2.bin")
```

---

## Credits & License

- **4DS Importer** by **Sev3n** & **Grok 3 (xAI)**  
- **Scene2.bin parsing** & Blender integration by **Blue Eagle**  

Licensed under the MIT License. See [LICENSE](./LICENSE) for details.

---

## Troubleshooting

- **Missing meshes?**  
  Ensure your “Mafia Root Folder” preference points to the parent of the folder containing `.4DS` files.  
- **Blender freezes?**  
  Upgrade to Blender 4.0+ and ensure the progress bar is visible.  

---

## Todo

- Progress bar
- cache.bin importer

Enjoy importing your Mafia 1 worlds into Blender!
