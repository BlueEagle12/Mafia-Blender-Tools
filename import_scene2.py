bl_info = {
    "name": "Mafia Scene2.bin Importer",
    "author": "Blue Eagle",
    "version": (1, 3),
    "blender": (4, 0, 0),
    "location": "File > Import > Mafia Scene2 (.bin)",
    "category": "Import-Export",
}

import os
import struct
import bpy
import math
from mathutils import Quaternion
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty

# Constants from C# enums
CHUNK_ROOT_TYPES      = (0x4000, 0xAE20)
CHUNK_OBJECT_TYPES    = (0x4010, 0xAE21)

PROP_TYPE_NORMAL      = 0x4011
PROP_NAME             = 0x0010
PROP_NAME_SPECIAL     = 0xAE23
PROP_MODEL            = 0x2012
PROP_POSITION         = 0x0020
PROP_PARENT           = 0x4020
PROP_ROTATION         = 0x0022
PROP_SCALE            = 0x002D
PROP_HIDDEN           = 0x4033
PROP_LIGHT_MAIN       = 0x4040

LIGHT_TYPE            = 0x4041
LIGHT_COLOR           = 0x0026
LIGHT_POWER           = 0x4042
LIGHT_RANGE           = 0x4044
LIGHT_UNKNOWN         = 0x4043


# ObjectType values
OBJ_NONE              = 0x00
OBJ_LIGHT             = 0x02
OBJ_CAMERA            = 0x03
OBJ_SOUND             = 0x04
OBJ_MODEL             = 0x09
OBJ_OCCLUDER          = 0x0C
OBJ_SECTOR            = 0x99
OBJ_LIGHTMAP          = 0x9A
OBJ_SCRIPT            = 0x9B

# Lookup tables
OBJECT_TYPES = {
    OBJ_NONE:     "None",
    OBJ_LIGHT:    "Light",
    OBJ_CAMERA:   "Camera",
    OBJ_SOUND:    "Sound",
    OBJ_MODEL:    "Model",
    OBJ_OCCLUDER: "Occluder",
    OBJ_SECTOR:   "Sector",
    OBJ_LIGHTMAP: "Lightmap",
    OBJ_SCRIPT:   "Script",
}

LIGHT_TYPES = {
    0x01: 'POINT',
    0x02: 'SPOT',
    0x03: 'SUN',
    0x04: 'AREA',
    0x05: 'POINT',
    0x06: 'POINT',
    0x08: 'AREA',
}

try:
    from .import_4ds import The4DSImporter
except ImportError:
    from import_4ds import The4DSImporter

class Scene2Importer(The4DSImporter):
    def build_armature(self):
        try:
            super().build_armature()
        except NotImplementedError as e:
            if "Non-uniform armature scaling" in str(e):
                print(f"Scene2Importer: skipping armature due to non-uniform scale ({e})")
                return
            raise

class Scene2Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    maps_folder: StringProperty(
        name="Mafia Root Folder",
        subtype='DIR_PATH',
        default="",
        description="Root folder for .4DS files"
    ) # type: ignore

    def draw(self, context):
        self.layout.prop(self, "maps_folder")

class ImportScene2(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.scene2"
    bl_label = "Import Scene2.bin"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".bin"
    filter_glob: StringProperty(default="*.bin", options={'HIDDEN'})

    light_power: bpy.props.FloatProperty(
    name="Light Power",
    default=100.0,
    min=0.0,
    max=10000.0,
    description="Power value for imported lights"
    ) # type: ignore

    sun_power: bpy.props.FloatProperty(
    name="Sun Power",
    default=5.0,
    min=0.0,
    max=10000.0,
    description="Power value for imported sun(s)"
    ) # type: ignore



    def execute(self, context):
        prefs = context.preferences.addons[__name__].preferences
        maps_dir = bpy.path.abspath(prefs.maps_folder) if prefs.maps_folder else None
        imp_dir = os.path.dirname(self.filepath)
        self.search_dirs = [d for d in (maps_dir, imp_dir) if d]
        self.scene = context.scene
        self.wm = context.window_manager
        self.name_to_empty = {}
        self.parent_links  = []

        self.queue = self._parse_scene2(self.filepath)
        self.total = len(self.queue)
        
        if not self.queue:
            self.report({'WARNING'}, "No entities found in scene2.bin")
            return {'CANCELLED'}

        self.wm.progress_begin(0, self.total)
        bpy.app.timers.register(self._step_import)
        return {'RUNNING_MODAL'}

    def _step_import(self):
        if not self.queue:
            self._apply_parenting()
            self.wm.progress_end()
            return None

        task = self.queue.pop(0)
        done = self.total - len(self.queue)

        if task['obj_type'] == OBJ_LIGHT:
            self._create_light(task)
        else:
            self._import_model(task)

        self.wm.progress_update(done)
        #bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        return 0.01

    def _import_model(self, obj):

        model_name = obj.get('model')
        if not model_name:
            target_obj = bpy.data.objects.get(obj.get('name'))
            if target_obj:

                if obj['pos']:
                    target_obj.location        = obj['pos']
                if obj['rot']:
                    target_obj.rotation_euler  = obj['rot']
                if obj['scale']:
                    target_obj.scale           = obj['scale']      
                if obj['hidden']:
                    target_obj.hide_viewport = True
                    target_obj.hide_render = True
            return
    
        path = self._find_mesh(obj['model'])
        if not path:
            self.report({'WARNING'}, f"Missing mesh: {obj['model']}")
            return
        

        before = set(self.scene.objects)
        imp4ds = Scene2Importer(path)
        imp4ds.import_file()
        for new in set(self.scene.objects) - before:

            if obj['hidden']:
                new.hide_viewport = True
                new.hide_render = True

            if new.parent is None:
                empty = bpy.data.objects.new(obj['name'] + "_root", None)
                self.scene.collection.objects.link(empty)
                new.parent = empty
                empty.location        = obj['pos']
                empty.rotation_euler  = obj['rot']
                empty.scale           = obj['scale']
                self.name_to_empty[obj['name']] = empty

                pName = obj.get('parent_name')
                if pName and pName != "Primary sector":
                    self.parent_links.append((empty, pName))

    def _create_light(self, lt):
        # Ensure we have a light entry

        code = lt.get('light_type')

        if 'light_type' not in lt:
            return
        
        # Map Mafia light code to Blender light type string
        ltype = LIGHT_TYPES.get(code, 'POINT')

        name = ltype#lt.get('name', ltype)

        # Create new light data block
        ld = bpy.data.lights.new(name=name, type=ltype)

        # assign color, intensity (energy), and range
        color = lt.get('color')
        if color is None:
            color = (1.0, 1.0, 1.0)
        ld.color = color

        power = lt.get('power')

        if ltype == "SUN":
            ld.energy = (power if power is not None else 250.0)*self.sun_power
        elif ltype == "POINT":
            ld.energy = (power if power is not None else 250.0)*self.light_power
        else:
            ld.energy = (power if power is not None else 250.0)*self.light_power

        rng = lt.get('range')
        if rng is not None:
            ld.cutoff_distance = rng

        if ltype == "SPOT":
            angle = lt.get('angle')
            if angle is not None:
                ld.spot_size = angle

        # Create the light object and link it
        lo = bpy.data.objects.new(name, ld)
        pos = lt.get('pos')
        if pos:
            lo.location = pos

        rot = lt.get('rot')
        if rot:
            lo.rotation_euler = rot
            lo.rotation_euler.x += math.radians(90)

        self.scene.collection.objects.link(lo)

        return None

    def _find_mesh(self, name):
        for d in self.search_dirs:
            f = os.path.join(d, name)
            if os.path.isfile(f):
                return f
        for d in self.search_dirs:
            for root, _, files in os.walk(d):
                for fi in files:
                    if fi.lower() == name.lower():
                        return os.path.join(root, fi)
        return None

    def _read_header(self, f):
        return struct.unpack('<HI', f.read(6))

    def _read_cstr(self, f):
        data = bytearray()
        while True:
            b = f.read(1)
            if not b or b == b'\x00': break
            data += b
        return data.decode('utf-8', errors='ignore')

    def _parse_scene2(self, path):
        tasks = []
        with open(path, 'rb') as f:
            _, size = self._read_header(f)
            self._recurse(f, 6, size, tasks)
        return tasks

    def _recurse(self, f, start, end, tasks):
        ptr = start
        while ptr + 6 <= end:
            f.seek(ptr)
            ctype, csize = self._read_header(f)
            dstart, dend = ptr + 6, ptr + csize
            if ctype in CHUNK_ROOT_TYPES:
                self._recurse(f, dstart, dend, tasks)
            elif ctype in CHUNK_OBJECT_TYPES:
                ent = self._extract_props(f, dstart, dend)
                tasks.append(ent)
            ptr += csize


    def _apply_parenting(self):
        print('Applying Parenting')

        for child, parent_name in self.parent_links:
            parent = self.name_to_empty.get(parent_name)

            if parent is None:
                parent = self.scene.objects.get(parent_name)
                if parent:
                    print(f"Found scene object for parent '{parent_name}'")

            if child and parent:
                child.parent = parent
                print(parent_name + ' Parented')
            else:
                self.report(
                    {'WARNING'},
                    f"Cannot parent '{child.name}' under '{parent_name}'"
                )

    def _read_light_props(self, f, start, end, props):
        ptr = start
        while ptr + 6 <= end:
            f.seek(ptr)
            ptype, psize = struct.unpack('<HI', f.read(6))
            f.seek(ptr + 6)

            if ptype == LIGHT_TYPE:
                props['light_type'] = struct.unpack('<I', f.read(4))[0]
                props['obj_type'] = OBJ_LIGHT

            elif ptype == LIGHT_COLOR:
                props['color'] = struct.unpack('<3f', f.read(12))
            elif ptype == LIGHT_POWER:
                props['power'] = struct.unpack('<f', f.read(4))[0]
            elif ptype == LIGHT_RANGE:
                near = struct.unpack('<f', f.read(4))[0]
                far  = struct.unpack('<f', f.read(4))[0]
                props['range'] = far
            elif ptype == LIGHT_UNKNOWN:
                unk1 = struct.unpack('<f', f.read(4))[0]
                angle  = struct.unpack('<f', f.read(4))[0]
                props['angle'] = angle


            ptr += psize

    def _extract_props(self, f, start, end):
        # Clean, readable extraction of chunk properties
        props = {
            'name':       None,
            'model':      None,
            'pos':        None,
            'rot':        None,
            'scale':      None,
            'light_type': None,
            'color':      None,
            'power':      None,
            'range':      None,
            'angle':      None,
            'parent_name':None,
            'hidden':     None,
            'obj_type':   OBJ_MODEL
        }

        ptr = start
        while ptr + 6 <= end:
            f.seek(ptr)
            ptype, psize = self._read_header(f)
            f.seek(ptr + 6)


            if ptype == PROP_PARENT:
                # read the nested “object” header inside Parent
                sub_type, sub_size = self._read_header(f)
                sub_start = ptr + 6
                sub_end   = ptr + psize
                scan = sub_start
                # scan sub-chunks for a Name property
                while scan + 6 <= sub_end:
                    f.seek(scan)
                    stype, ssize = self._read_header(f)
                    f.seek(scan + 6)
                    if stype in (PROP_NAME, PROP_NAME_SPECIAL):
                        props['parent_name'] = self._read_cstr(f)
                        break
                    scan += ssize

                ptr += psize
                continue

            if ptype in (PROP_NAME, PROP_NAME_SPECIAL):
                props['name'] = self._read_cstr(f)

            elif ptype == PROP_MODEL:
                props['model'] = (
                    self._read_cstr(f)
                    .lower()
                    .replace('.i3d', '.4ds')
                )

            elif ptype == PROP_POSITION:
                x, y, z = struct.unpack('<3f', f.read(12))
                props['pos'] = (x, z, y)

            elif ptype == PROP_ROTATION:
                q = struct.unpack('<4f', f.read(16))
                props['rot'] = (
                    Quaternion((q[0], q[1], q[3], q[2]))
                    .to_euler('XYZ')
                )
            elif ptype == PROP_SCALE:
                sx, sy, sz = struct.unpack('<3f', f.read(12))
                props['scale'] = (sx, sz, sy)

            elif ptype == PROP_TYPE_NORMAL:
                code = struct.unpack('<I', f.read(4))[0]
                props['obj_type'] = code

            elif ptype == PROP_HIDDEN:
                props['hidden'] = True

            elif ptype == PROP_LIGHT_MAIN:
                sub_ptr = ptr + 6
                end_inner = ptr + 6 + psize
                while sub_ptr + 6 <= end_inner:
                    f.seek(sub_ptr)
                    raw = f.read(6)
                    if len(raw) != 6:
                        print(f"[WARN] Truncated light block at {sub_ptr}")
                        break
                    sub_type, sub_size = struct.unpack('<HI', raw)
                    self._read_light_props(f,ptr + 6 ,ptr + psize ,props)
                    sub_ptr += sub_size

            ptr += psize

        return props


def menu_func(self, context):
    self.layout.operator(
        ImportScene2.bl_idname,
        text="Mafia Scene2 (.bin)"
    )


def register():
    bpy.utils.register_class(Scene2Prefs)
    bpy.utils.register_class(ImportScene2)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    bpy.utils.unregister_class(ImportScene2)
    bpy.utils.unregister_class(Scene2Prefs)

if __name__ == "__main__":
    register()
