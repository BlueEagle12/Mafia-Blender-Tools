# =====================================
#  Mafia Shared Importer - Blender Add-on
# =====================================

import os
import gc
import math
import bpy
from bpy.props import StringProperty, IntProperty, FloatProperty, EnumProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper


# -------------------------------------
# References
# -------------------------------------


from .import_4ds import The4DSImporter
from .import_scene2 import Scene2Importer
from .import_cache import CacheBinImporter

# -------------------------------------
# Constants
# -------------------------------------

LIGHT_TYPES = {
    0x01: 'POINT',
    0x02: 'SPOT',
    0x03: 'SUN',
    0x04: 'AREA',
    0x05: 'POINT',
    0x06: 'POINT',
    0x08: 'AREA',
}

# === Object Type Values ===
OBJ_MODEL    = 0x09
OBJ_LIGHT    = 0x02
OBJ_CAMERA   = 0x03
OBJ_SOUND    = 0x04
OBJ_OCCLUDER = 0x0C
OBJ_SECTOR   = 0x99
OBJ_LIGHTMAP = 0x9A
OBJ_SCRIPT   = 0x9B

# === Special Object Type Values ===
OBJ_PHYSICAL       = 0x23
OBJ_PLAYER         = 0x02
OBJ_CHARACTER      = 0x1B
OBJ_CAR            = 0x04
OBJ_DOOR           = 0x06
OBJ_DOG            = 0x15
OBJ_PUMPER         = 0x19
OBJ_PUBLIC_VEHICLE = 0x08
OBJ_SCRIPT_SPECIAL = 0x05

OBJECT_TYPE_ITEMS = [
    ('MODEL',    "Model", ""),
    ('LIGHT',    "Light", ""),
    ('CAMERA',   "Camera", ""),
    ('SOUND',    "Sound", ""),
    ('OCCLUDER', "Occluder", ""),
    ('SECTOR',   "Sector", ""),
    ('LIGHTMAP', "Lightmap", ""),
    ('SCRIPT',   "Script", ""),
]

SPECIAL_TYPE_ITEMS = [
    ('PHYSICAL',        "Physical", ""),
    ('PLAYER',          "Player", ""),
    ('CHARACTER',       "Character", ""),
    ('CAR',             "Car", ""),
    ('DOOR',            "Door", ""),
    ('DOG',             "Dog", ""),
    ('PUMPER',          "Pumper", ""),
    ('PUBLIC_VEHICLE',  "Public Vehicle", ""),
    ('SCRIPT_SPECIAL',  "Script (Special)", ""),
]

object_type_map = {
    'MODEL': OBJ_MODEL,
    'LIGHT': OBJ_LIGHT,
    'CAMERA': OBJ_CAMERA,
    'SOUND': OBJ_SOUND,
    'OCCLUDER': OBJ_OCCLUDER,
    'SECTOR': OBJ_SECTOR,
    'LIGHTMAP': OBJ_LIGHTMAP,
    'SCRIPT': OBJ_SCRIPT,
}

special_type_map = {
    'PHYSICAL':        OBJ_PHYSICAL,
    'PLAYER':          OBJ_PLAYER,
    'CHARACTER':       OBJ_CHARACTER,
    'CAR':             OBJ_CAR,
    'DOOR':            OBJ_DOOR,
    'DOG':             OBJ_DOG,
    'PUMPER':          OBJ_PUMPER,
    'PUBLIC_VEHICLE':  OBJ_PUBLIC_VEHICLE,
    'SCRIPT_SPECIAL':  OBJ_SCRIPT_SPECIAL,
}



# -- Globals used during import batching --
to_link        = []  # (collection, object) pairs to link post-import
instance_queue = []  # Deferred instances to create after all models are loaded

name_to_empty = {}   # Maps object names to their corresponding empty objects
parent_links  = []   # List of (child, parent_name) pairs to resolve after import

# -- Global lighting intensity multipliers --
GLOBAL_SUN_POWER   = 1.0
GLOBAL_LIGHT_POWER = 100.0


def print_debug(error):
    prefs = bpy.context.preferences.addons["Mafia_Formats"].preferences
    if prefs.debug_logging:
        print(error)    


# -- Preferences Panel --
class MafiaPrefs(bpy.types.AddonPreferences):
    bl_idname = "Mafia_Formats"

    maps_folder: StringProperty(
        name="Mafia Root Folder",
        subtype='DIR_PATH',
        default="",
        description="Root folder for .4DS files"
    ) # type: ignore

    batch_size: IntProperty(
        name="Batch Size",
        description="Number of objects to import per batch",
        default=500,
        min=1,
        max=10000
    ) # type: ignore

    import_lods: BoolProperty(
        name="Import LODs",
        description="If disabled, only base models (LOD 0) will be imported",
        default=False
    ) # type: ignore

    debug_logging: BoolProperty(
        name="Enable Debug Logging",
        default=False,
        description="Print detailed import debug information"
    ) # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "maps_folder")
        layout.prop(self, "batch_size")
        layout.prop(self, "import_lods")
        layout.prop(self, "debug_logging")



# -- Presents --
class MAFIA_OT_SetImportPreset(bpy.types.Operator):
    bl_idname = "mafia.set_import_preset"
    bl_label = "Set Import Preset"

    preset: bpy.props.EnumProperty(
        items=[
            ("DEFAULT", "Default", "Default selection"),
            ("ALL", "All Types", "Enable all object types"),
            ("NONE", "None", "Disable all object types"),
        ]
    ) # type: ignore

    def execute(self, context):
        op = context.operator
        if not hasattr(op, "filter_object_types") or not hasattr(op, "filter_special_types"):
            print({'ERROR'}, "Operator missing required properties.")
            return {'CANCELLED'}

        if self.preset == "DEFAULT":
            op.filter_object_types = {'MODEL', 'LIGHT', 'SECTOR', 'OCCLUDER'}
            op.filter_special_types = {'PHYSICAL', 'CAR', 'PUBLIC_VEHICLE'}
        elif self.preset == "ALL":
            op.filter_object_types = {item[0] for item in OBJECT_TYPE_ITEMS}
            op.filter_special_types = {item[0] for item in SPECIAL_TYPE_ITEMS}
        elif self.preset == "NONE":
            op.filter_object_types.clear()
            op.filter_special_types.clear()

        return {'FINISHED'}
    

# -- 4DS Importer Wrapper --
class Mafia_Formats(The4DSImporter):
    def build_armature(self):
        try:
            super().build_armature()
        except NotImplementedError as e:
            if "Non-uniform armature scaling" in str(e):
                print_debug(f"[SKIP] Skipping armature due to non-uniform scale: {e}")
                return
            raise


def is_background():
    return bpy.app.background


# -- Class: .Bin Importer --
class ImportMafiaBIN(bpy.types.Operator, ImportHelper):
    bl_idname = "import_mafia.bin"
    bl_label = "Import Mafia .bin"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Import Mafia 1 scene2.bin or cache.bin files"

    filename_ext = ".bin"
    filter_glob: StringProperty(
        default="*.bin",
        options={'HIDDEN'}
    ) # type: ignore

    light_power: FloatProperty(
        name="Light Power",
        default=100.0,
        min=0.0,
        max=10000.0,
        description="Power value for imported lights"
    ) # type: ignore

    sun_power: FloatProperty(
        name="Sun Power",
        default=5.0,
        min=0.0,
        max=10000.0,
        description="Power value for imported sun(s)"
    ) # type: ignore

    filter_object_types: EnumProperty(
        name="General Types",
        items=OBJECT_TYPE_ITEMS,
        options={'ENUM_FLAG'},
        default={'MODEL', 'LIGHT', 'SECTOR', 'OCCLUDER'},
        description="Importable object types"
    ) # type: ignore

    filter_special_types: EnumProperty(
        name="Special Types",
        items=SPECIAL_TYPE_ITEMS,
        options={'ENUM_FLAG'},
        default={'PHYSICAL', 'CAR', 'PUBLIC_VEHICLE'},
        description="Importable special object types"
    ) # type: ignore



    def execute(self, context):
        name = os.path.basename(self.filepath).lower()
        global GLOBAL_SUN_POWER, GLOBAL_LIGHT_POWER
        GLOBAL_SUN_POWER = self.sun_power
        GLOBAL_LIGHT_POWER = self.light_power

        importer_map = {
            "scene2.bin": Scene2Importer,
            "cache.bin": CacheBinImporter,
        }

        importer_class = importer_map.get(name)
        if not importer_class:
            print({'ERROR'}, "Only 'scene2.bin' and 'cache.bin' are supported.")
            return {'CANCELLED'}

        importer = importer_class(self.filepath, start_import_timer)
        importer.operator = self

        # CLI automation detection: do everything in one go if running headless
        if is_background():
            # Synchronous import:
            if name == "scene2.bin":
                queue = importer.parse_scene2(self.filepath)
            elif name == "cache.bin":
                queue = importer.parse_cache(self.filepath)
            else:
                print(f"[SKIP] Unknown .bin file: {name}")
                return {'CANCELLED'}

            total = len(queue)
            if not queue:
                print(f"[SKIP] No entities found in {name}")
                return {'CANCELLED'}

            scene_name = os.path.basename(os.path.dirname(self.filepath))
            collection = getCollection(None, scene_name)

            enabled_types = {
                object_type_map[k]
                for k in self.filter_object_types
                if k in object_type_map
            }
            special_types = {
                special_type_map[k]
                for k in self.filter_special_types
                if k in special_type_map
            }

            total = len(queue)
            for idx, task in enumerate(queue):
                object_type = task.get('obj_type', 0x00)
                special_type = task.get('special_type', 0x00)

                if object_type in enabled_types or special_type in special_types:
                    if object_type == OBJ_LIGHT:
                        create_light(task, collection)
                    else:
                        target_collection = getCollection(None, task.get('collection'), parent=collection)
                        import_model(task, target_collection)

                # Print progress status every 100 objects

                if (idx + 1) % 100 == 0 or (idx + 1) == total:
                    print(f"Processed {idx + 1}/{total} objects")
                
                if (idx + 1) == total:
                    print(f"Finishing Task")

            end_import_timer()

            print('END (synchronous batch)')
            return {'FINISHED'}

        # GUI mode: async timer as before
        return importer.run(context)


    
    def draw(self, context):
        layout = self.layout

        layout.prop(self, "light_power")
        layout.prop(self, "sun_power")

        layout.separator()

        # --- Object Type Filters ---
        box = layout.box()
        box.label(text="Import Filters", icon='FILTER')

        col = box.column(align=True)
        col.label(text="General Object Types:")
        col.prop_menu_enum(self, "filter_object_types", text="Select General Types")

        col.separator()

        col.label(text="Special Object Types:")
        col.prop_menu_enum(self, "filter_special_types", text="Select Special Types")

        # --- Presets ---
        preset_row = box.row(align=True)
        preset_row.label(text="Presets:")
        preset_row.operator("mafia.set_import_preset", text="Default").preset = "DEFAULT"
        preset_row.operator("mafia.set_import_preset", text="All").preset = "ALL"
        preset_row.operator("mafia.set_import_preset", text="None").preset = "NONE"



def menu_func(self, context):
    self.layout.operator(
        ImportMafiaBIN.bl_idname,
        text="Mafia: Import Cache & Scene2 (.bin)",
    )

# -- Utility: Get or create a collection and link it under the specified parent --
def getCollection(collection=None, collection_name=None, parent=None):
    if collection:
        return collection

    collection_name = collection_name or "4DS_Collection"

    collection = bpy.data.collections.get(collection_name)
    if not collection:
        collection = bpy.data.collections.new(collection_name)

    link_target = parent or bpy.context.scene.collection

    if collection.name not in link_target.children:
        link_target.children.link(collection)

    return collection



# -- Begin import process using asynchronous per-frame timer --
def start_import_timer(operator_instance, on_complete=None, scene_name=None):

    scene_name = scene_name or "Collection"
    collection = getCollection(None, scene_name)

    wm = operator_instance.wm
    total = operator_instance.total
    
    instance_queue.clear()
    to_link.clear()
    name_to_empty.clear()
    parent_links.clear()

    reset_model_cache()


    print('Starting')
    
    if not is_background():
        
        wm.progress_begin(0, total)

        bpy.context.preferences.edit.use_global_undo = False


    
        def timer_callback():
            return _step_import(operator_instance, on_complete, collection)

        bpy.app.timers.register(timer_callback)
        return {'RUNNING_MODAL'}


# -- Finalize import and link all deferred objects into their collections --
def end_import_timer():
    for collection, obj in to_link:
        try:
            if obj.name not in collection.objects:
                collection.objects.link(obj)
        except ReferenceError:
            print_debug(f"[WARN] Skipping freed object during linking: {obj}")

    apply_parenting()

    # Only do UI redraw if we're NOT in is_background()/CLI mode
    if not is_background():
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)

        bpy.context.preferences.edit.use_global_undo = True
        bpy.context.view_layer.update()

    gc.collect()



# -- Per-frame batched import step --
def _step_import(self, on_complete=None, collection=None):
    if not self.queue:
        if on_complete:
            on_complete()
        end_import_timer()
        self.wm.progress_end()

        print('END')
        return None


    print('TIMER 1')

    prefs = bpy.context.preferences.addons["Mafia_Formats"].preferences
    batch_size = prefs.batch_size

    enabled_types = {
        object_type_map[k]
        for k in self.operator.filter_object_types
        if k in object_type_map
    }

    special_types = {
        special_type_map[k]
        for k in self.operator.filter_special_types
        if k in special_type_map
    }

    for _ in range(min(batch_size, len(self.queue))):
        task = self.queue.pop(0)
        done = self.total - len(self.queue)

        object_type = task.get('obj_type', 0x00)
        special_type = task.get('special_type', 0x00)

        print_debug(f"[TASK] obj_type={object_type}, special_type={special_type}")

        if object_type in enabled_types or special_type in special_types:
            if object_type == OBJ_LIGHT:
                create_light(task, collection)
            else:
                target_collection = getCollection(None, task.get('collection'), parent=collection)
                import_model(task, target_collection)

        self.wm.progress_update(done)

        if done % 200 == 0:
            gc.collect()

    return 0.01
    

# -- Import and instance a 4DS model --
def import_model(obj, collection):
    prefs = bpy.context.preferences.addons["Mafia_Formats"].preferences
    maps_dir = bpy.path.abspath(prefs.maps_folder) if prefs.maps_folder else None
    search_dirs = [maps_dir] if maps_dir else []

    if not hasattr(import_model, "_cache"):
        import_model._cache = {}
    model_cache = import_model._cache

    model_name = obj.get("model")
    object_name = obj.get("name")

    # Case: No model (non-4DS object) – just apply transform and parent later
    if not model_name:
        target_obj = bpy.data.objects.get(object_name)
        if target_obj:
            parent_name = obj.get("parent_name")
            if parent_name and parent_name != "Primary sector":
                print_debug(f"[SCENE] Parent Assigned {parent_name}")
                parent_links.append((target_obj, parent_name))

            target_obj.rotation_euler = obj.get("rot") or target_obj.rotation_euler
            target_obj.location = obj.get("pos") or target_obj.location
            target_obj.scale = obj.get("scale") or target_obj.scale

            if obj.get("hidden"):
                target_obj.hide_viewport = True
                target_obj.hide_render = True
        return

    # Check model cache
    cache_result = model_cache.get(model_name)
    empty = None
    duplicates = []

    if cache_result:
        print_debug(f"[INSTANCE] Instancing cached 4DS model: {model_name}")
        base_objects, cached_empty = cache_result
        original_to_duplicate = {}

        for base in base_objects:
            dup = bpy.data.objects.new(base.name, base.data)
            original_to_duplicate[base] = dup

            if base is cached_empty:
                empty = dup
                to_link.append((collection, empty))
            else:
                duplicates.append(dup)

        # Restore hierarchy
        for base, dup in original_to_duplicate.items():
            if base.parent and base.parent in original_to_duplicate:
                dup.parent = original_to_duplicate[base.parent]
                dup.matrix_basis = base.matrix_basis.copy()

    else:
        print_debug(f"[IMPORT] Loading new 4DS model: {model_name}")
        path = _find_mesh(model_name, search_dirs)
        if not path:
            print_debug(f"[MISSING] Mesh not found: {model_name}")
            return

        imp4ds = Mafia_Formats(path)
        duplicates = imp4ds.import_file()
        if not duplicates:
            print_debug(f"[SKIP] No importable objects in 4DS model: {model_name}")
            return

    # Link duplicates and handle parenting to empty
    for new in duplicates:
        if new is not empty:
            to_link.append((collection, new))

            if obj.get("hidden"):
                new.hide_viewport = True
                new.hide_render = True

            if new.parent is None:
                if empty is None:
                    empty = bpy.data.objects.new(object_name + "_root", None)
                    duplicates.append(empty)
                    to_link.append((collection, empty))

                new.matrix_parent_inverse = empty.matrix_world.inverted()
                new.parent = empty

    # Apply transform and store for hierarchy linking
    if empty:
        empty.location = obj.get("pos", empty.location)
        empty.rotation_euler = obj.get("rot", empty.rotation_euler)
        empty.scale = obj.get("scale", empty.scale)

        if object_name not in name_to_empty:
            name_to_empty[object_name] = empty

        parent = obj.get("parent_name")
        if parent and parent != "Primary sector":
            print_debug(f"[SCENE] Parent Assigned {parent}")
            parent_links.append((empty, parent))

        model_cache.setdefault(model_name, (duplicates, empty))


# -- Reset import model cache --
def reset_model_cache():
    if hasattr(import_model, "_cache"):
        import_model._cache.clear()


# -- Locate mesh file by name --
def _find_mesh(name, search_dirs):
    # Try direct match first
    for directory in search_dirs:
        filepath = os.path.join(directory, name)
        if os.path.isfile(filepath):
            return filepath

    # Fallback: recursive search by case-insensitive name
    lowered_name = name.lower()
    for directory in search_dirs:
        for root, _, files in os.walk(directory):
            for filename in files:
                if filename.lower() == lowered_name:
                    return os.path.join(root, filename)

    return None


# -- Create and configure a Blender light object from parsed data --
def create_light(lt, collection):
    if 'light_type' not in lt:
        return

    code = lt.get('light_type')
    light_type = LIGHT_TYPES.get(code, 'POINT')
    light_name = light_type

    light_data = bpy.data.lights.new(name=light_name, type=light_type)

    light_data.color = lt.get('color', (1.0, 1.0, 1.0))
    power = lt.get('power', 250.0)

    if light_type == "SUN":
        light_data.energy = power * GLOBAL_SUN_POWER
    else:
        light_data.energy = power * GLOBAL_LIGHT_POWER

    if 'range' in lt:
        light_data.cutoff_distance = lt['range']

    if light_type == "SPOT" and 'angle' in lt:
        light_data.spot_size = lt['angle']

    light_obj = bpy.data.objects.new(light_name, light_data)
    if 'pos' in lt:
        light_obj.location = lt['pos']
    if 'rot' in lt:
        rot = lt['rot']
        light_obj.rotation_euler = (rot[0] + math.radians(90), rot[1], rot[2])

    to_link.append((collection, light_obj))

    parent = lt.get('parent_name')
    if parent and parent != "Primary sector":
        print_debug(f"Parent Assigned {parent}")
        parent_links.append((light_obj, parent))



# -- Apply deferred parent-child relationships after all objects are loaded --
def apply_parenting():
    print_debug("[PARENT] Applying deferred parenting...")

    for child, parent_name in parent_links:
        parent = name_to_empty.get(parent_name)

        # Fallback to looking up in the scene if not found in name_to_empty
        if parent is None:
            parent = bpy.context.scene.objects.get(parent_name)
            if parent:
                print_debug(f"[PARENT] Found fallback parent in scene: {parent_name}")

        if child and parent:
            child.parent = parent
            print_debug(f"[PARENT] Set parent: {child.name} → {parent.name}")
        else:
            cname = getattr(child, "name", "UNKNOWN")
            print_debug(f"[WARN] Failed to resolve parent '{parent_name}' for: {cname}")


# =========================
# Wireframe Visibility Panel
# =========================

_wireframe_update_queue = []

def update_wireframe_visibility(self, context):
    global _wireframe_update_queue
    show = context.scene.show_wireframe_objs

    _wireframe_update_queue = [
        obj for obj in bpy.data.objects
        if obj.type == 'MESH' and obj.get("Mafia.wireframe") and obj.hide_viewport != (not show)
    ]

    bpy.app.timers.register(process_wireframe_queue, first_interval=0.01)


def process_wireframe_queue():
    global _wireframe_update_queue
    chunk_size = 100

    for _ in range(min(chunk_size, len(_wireframe_update_queue))):
        obj = _wireframe_update_queue.pop(0)
        obj.hide_viewport = not bpy.context.scene.show_wireframe_objs

    return 0.01 if _wireframe_update_queue else None


class VIEW3D_PT_wireframe_visibility(bpy.types.Panel):
    bl_label = "Mafia Sector Tools"
    bl_idname = "VIEW3D_PT_wireframe_visibility"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Display'

    def draw(self, context):
        self.layout.prop(context.scene, "show_wireframe_objs")


def register_props():
    from bpy.props import BoolProperty

    bpy.types.Scene.show_wireframe_objs = BoolProperty(
        name="Show Sector Objects",
        description="Toggle visibility of Mafia zone objects",
        default=True,
        update=update_wireframe_visibility
    )


def unregister_props():
    if hasattr(bpy.types.Scene, "show_wireframe_objs"):
        del bpy.types.Scene.show_wireframe_objs


classes = [
    VIEW3D_PT_wireframe_visibility,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    register_props()
    bpy.utils.register_class(MafiaPrefs)
    bpy.utils.register_class(ImportMafiaBIN)
    bpy.utils.register_class(MAFIA_OT_SetImportPreset)

    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)

    bpy.utils.unregister_class(MAFIA_OT_SetImportPreset)
    bpy.utils.unregister_class(ImportMafiaBIN)
    bpy.utils.unregister_class(MafiaPrefs)

    unregister_props()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

