bl_info = {
    "name": "Mafia Format Importer",
    "author": "Blue Eagle, Sev3n",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "File > Import",
    "description": "Imports Various Mafia 1 Formats",
    "category": "Import-Export",
}

#Original 4DS importer, exporter writen by Sev3n & Grok 3 (xAI). Heavily modified by Blue Eagle

from . import import_mafia, import_4ds, export_4ds

def register():
    import_mafia.register()
    import_4ds.register()
    export_4ds.register()

def unregister():
    import_mafia.unregister()
    import_4ds.unregister()
    export_4ds.unregister()