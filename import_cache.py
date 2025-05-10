bl_info = {
    "name": "Mafia Cache.bin Importer",
    "author": "Blue Eagle",
    "version": (1, 0),
    "blender": (4, 0, 0),
}

import os
import struct
from mathutils import Quaternion


class CacheBinImporter():
    def __init__(self, filepath, start_timer):
        self.filepath = filepath
        self.start_import_timer = start_timer

    def run(self, context):

        self.scene = context.scene
        self.wm = context.window_manager
        self.name_to_empty = {}
        self.parent_links  = []

        self.queue = self._parse_cache(self.filepath)

        folder_name = os.path.basename(os.path.dirname(self.filepath))

        self.total = len(self.queue)

        if not self.queue:
            print("[SKIP] No entities found in cache.bin")
            return {'CANCELLED'}
    
        return self.start_import_timer(self,on_complete=None, scene_name=folder_name)
    
    def _read_header(self, f):
        return struct.unpack('<HI', f.read(6))

    def _parse_cache(self, path):
        props = []
        with open(path, 'rb') as f:
            _, total_size = self._read_header(f)
            version = struct.unpack('<I', f.read(4))[0]

            ptr = f.tell()
            while ptr + 6 <= total_size - 4:
                f.seek(ptr)
                chunk_type, chunk_size = self._read_header(f)

                name_len = struct.unpack('<I', f.read(4))[0]
                object_name = f.read(name_len).decode('utf-8', errors='ignore')

                bounds = f.read(0x4C)
                header_size = 6 + 4 + name_len + 0x4C
                instance_start = f.tell()

                while f.tell() < instance_start + chunk_size - header_size:
                    inst_type, inst_size = self._read_header(f)
                    model_len = struct.unpack('<I', f.read(4))[0]
                    model = f.read(model_len).decode('utf-8', errors='ignore').lower().replace('.i3d', '.4ds')

                    name = model.removesuffix('.i3d').removesuffix('.4ds')

                    pos = (struct.unpack('<3f', f.read(12)))
                    rot = (struct.unpack('<4f', f.read(16)))
                    scale = (struct.unpack('<3f', f.read(12)))
                    unk0 = struct.unpack('<I', f.read(4))[0]
                    scale2 = (struct.unpack('<3f', f.read(12)))

                    props.append({
                        'name': name,
                        'model': model,
                        'pos': (pos[0],pos[2],pos[1]),
                        'rot': Quaternion((rot[0], rot[1], rot[3], rot[2])).to_euler('XYZ'),
                        'scale': (scale[0],scale[2],scale[1]),
                        'scale2': (scale2[0],scale2[2],scale2[1]),
                        'unk0': unk0,
                        'obj_type': 0x09,  # Same as OBJ_MODEL
                        'hidden': None,
                        'collection': object_name,
                    })

                ptr += chunk_size

        return props

def register():
    pass

def unregister():
    pass

if __name__ == "__main__":
    register()
