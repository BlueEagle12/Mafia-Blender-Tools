bl_info = {
    "name": "Mafia Scene2.bin Importer",
    "author": "Blue Eagle",
    "version": (1, 3),
    "blender": (4, 0, 0),
}

import os
import struct
from mathutils import Vector, Quaternion


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


class Scene2Importer:
    def __init__(self, filepath, start_timer):
        self.filepath = filepath
        self.start_import_timer = start_timer

    def run(self, context):

        self.scene = context.scene
        self.wm = context.window_manager
        self.name_to_empty = {}
        self.parent_links  = []

        self.queue = self._parse_scene2(self.filepath)
        self.total = len(self.queue)

        folder_name = os.path.basename(os.path.dirname(self.filepath))

        if not self.queue:
            print("[SKIP] No entities found in scene2.bin")
            return {'CANCELLED'}

        return self.start_import_timer(self, on_complete=self._apply_parenting, scene_name=folder_name)


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
        print("[PARENT] Parenting scene objects")


        for child, parent_name in self.parent_links:
            parent = self.name_to_empty.get(parent_name)

            if parent is None:
                parent = self.scene.objects.get(parent_name)
                if parent:
                    print(f"[PARENT] Found parent object in scene: {parent_name}")

            if child and parent:
                child.parent = parent
                print(f"[PARENT] Set parent for object: {child.name} → {parent.name}")
            else:
                print(f"[WARN] Failed to resolve parent '{parent_name}' for model: {child.name}")





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


def register():
    pass

def unregister():
    pass

if __name__ == "__main__":
    register()
