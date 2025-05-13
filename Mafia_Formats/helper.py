import struct
from mathutils import Quaternion, Vector, Matrix
from datetime import datetime

class Util:
    # ----------------------------
    # Quaternion
    # ----------------------------

    @staticmethod
    def read_quat(f, reorder=False):
        """Read a quaternion (w, x, y, z) from binary."""
        w, x, y, z = struct.unpack("<4f", f.read(16))

        if reorder:
            return Quaternion((w, x, z, y))
        else:
            return Quaternion((w, x, y, z))

    @staticmethod
    def write_quat(f, quat, reorder=False):
        """Write a quaternion (x, y, z, w) to binary."""
        if reorder:
            f.write(struct.pack("<4f", quat.w, quat.x, quat.z, quat.y))
        else:
            f.write(struct.pack("<4f", quat.w, quat.x, quat.y, quat.z))


    # ----------------------------
    # Vectors
    # ----------------------------

    @staticmethod
    def read_vector3(f, reorder=False):
        """Read a Vector3 (x, y, z) from binary."""
        x, y, z = struct.unpack("<3f", f.read(12))
        if reorder:
            return Vector((x, z, y))
        else:
            return Vector((x, y, z))
    
    @staticmethod
    def read_vector2(f):
        """Read a Vector2 (x, y) from binary."""
        x, y = struct.unpack("<2f", f.read(8))
        return Vector((x, y))

    @staticmethod
    def write_vector3(f, vec, reorder=False):
        """Write a Vector3 (x, y, z) to binary."""

        if not isinstance(vec, Vector):
            vec = Vector(vec)

        if reorder:
            f.write(struct.pack("<3f", vec.x, vec.z, vec.y))
        else:
            f.write(struct.pack("<3f", vec.x, vec.y, vec.z))

    @staticmethod
    def write_vector2(f, vec):

        if not isinstance(vec, Vector):
            vec = Vector(vec)
        """Write a Vector2 (x, y) to binary."""
        f.write(struct.pack("<2f", vec.x, vec.y))

    @staticmethod
    def read_vector_4(f):
        return struct.unpack("<4f", f.read(16))


    # ----------------------------
    # Matrix
    # ----------------------------

    @staticmethod
    def read_matrix4x4(f):
        """Read a 4x4 matrix from binary (column-major)."""
        values = struct.unpack("<16f", f.read(64))
        return Matrix([values[i:i+4] for i in range(0, 16, 4)])


    @staticmethod
    def write_matrix4x4(f, matrix):
        flat = [matrix[i][j] for i in range(4) for j in range(4)]
        f.write(struct.pack("<16f", *flat))

    # ----------------------------
    # Strings
    # ----------------------------

    @staticmethod
    def read_string(f, return_length=False):
        length = struct.unpack("<B", f.read(1))[0]
        if length == 0:
            return ("", 0) if return_length else ""
        
        data = f.read(length).decode("windows-1250", errors="ignore")
        return (data, length) if return_length else data

    @staticmethod
    def read_string32(f):
        length = struct.unpack('<I', f.read(4))[0]
        return f.read(length).decode('utf-8', errors='ignore'), length

    @staticmethod
    def read_int_16(f):
        return struct.unpack("<H", f.read(2))[0]

    def read_uint_8(f):
        return struct.unpack("<B", f.read(1))[0]

    @staticmethod
    def read_header(f, raw=False):
        if raw:
            return struct.unpack('<HI', raw)
        else:
            return struct.unpack('<HI', f.read(6))

    @staticmethod
    def read_terminated_string(f):
        data = bytearray()
        while True:
            b = f.read(1)
            if not b or b == b'\x00': break
            data += b
        return data.decode('utf-8', errors='ignore')
    
    @staticmethod
    def read_string_fixed(f, length):
        return f.read(length).decode('utf-8', errors='ignore')

    @staticmethod
    def serialize_header(f, version):
        f.write(b"4DS\0")

        Util.write_int_16(f, version)

        now = datetime.now()
        epoch = datetime(1601, 1, 1)
        delta = now - epoch
        filetime = int(delta.total_seconds() * 1e7)
        f.write(struct.pack("<Q", filetime))

    @staticmethod
    def write_string(f, string):
        encoded = string.encode("windows-1250", errors="replace")
        length = len(encoded)
        if length > 255:
            raise ValueError("String too long")
        f.write(struct.pack("<B", length))
        if length > 0:
            f.write(encoded)

    @staticmethod
    def write_uint_8(f, string):
        f.write(struct.pack("<B", string))


    @staticmethod
    def write_int_16(f, string):
        f.write(struct.pack("<H", string))

    # ----------------------------
    # Numbers
    # ----------------------------

    @staticmethod
    def read_int_32(f):
        return struct.unpack('<I', f.read(4))[0]

    @staticmethod
    def read_float_32(f):
        return struct.unpack('<f', f.read(4))[0]
    
    @staticmethod
    def write_string_uint32(f, string):
        encoded = string.encode("ascii")
        f.write(struct.pack("<I", len(encoded)))
        f.write(encoded)

    @staticmethod
    def write_int_32(f, string):
        f.write(struct.pack("<I", string))

    @staticmethod
    def write_float_32(f, string):
        f.write(struct.pack("<f", string))

    @staticmethod
    def read_face_indices(f):
        return struct.unpack("<3H", f.read(6))

    @staticmethod
    def write_face_indices(f, indices):
        if len(indices) != 3:
            raise ValueError("Face must have exactly 3 indices")
        f.write(struct.pack("<3H", *indices))

    @staticmethod
    def write_float_array(f, values):
        f.write(struct.pack(f"<{len(values)}f", *values))

    @staticmethod
    def write_uint16_array(f, data):
        f.write(struct.pack(f"<{len(data)}H", *data))

    @staticmethod
    def write_BB(f, values):
        if len(values) != 2:
            raise ValueError("Expected exactly two bytes")
        f.write(struct.pack("<BB", *values))