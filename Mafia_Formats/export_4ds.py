import struct
import bpy
import bmesh
from mathutils import Matrix, Vector
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper

from .helper import Util


# ----------------------------------
# File Version Constants
# ----------------------------------
VERSION_MAFIA     = 29
VERSION_HD2       = 41
VERSION_CHAMELEON = 42

# ----------------------------------
# Frame Type Constants
# ----------------------------------
FRAME_VISUAL     = 1
FRAME_LIGHT      = 2
FRAME_CAMERA     = 3
FRAME_SOUND      = 4
FRAME_SECTOR     = 5
FRAME_DUMMY      = 6
FRAME_TARGET     = 7
FRAME_USER       = 8
FRAME_MODEL      = 9
FRAME_JOINT      = 10
FRAME_VOLUME     = 11
FRAME_OCCLUDER   = 12
FRAME_SCENE      = 13
FRAME_AREA       = 14
FRAME_LANDSCAPE  = 15

# ----------------------------------
# Visual Type Constants
# ----------------------------------
VISUAL_OBJECT      = 0
VISUAL_LITOBJECT   = 1
VISUAL_SINGLEMESH  = 2
VISUAL_SINGLEMORPH = 3
VISUAL_BILLBOARD   = 4
VISUAL_MORPH       = 5
VISUAL_LENS        = 6
VISUAL_PROJECTOR   = 7
VISUAL_MIRROR      = 8
VISUAL_EMITOR      = 9
VISUAL_SHADOW      = 10
VISUAL_LANDPATCH   = 11


# ----------------------------------
# Material Constants
# ----------------------------------

MTL_DIFFUSETEX          = 0x00040000
MTL_COLORED             = 0x08000000
MTL_MIPMAP              = 0x00800000
MTL_ANIMTEXDIFF         = 0x04000000
MTL_ANIMTEXALPHA        = 0x02000000
MTL_DOUBLESIDED         = 0x10000000
MTL_ENVMAP              = 0x00080000
MTL_NORMTEXBLEND        = 0x00000100
MTL_MULTIPLYTEXBLEND    = 0x00000200
MTL_ADDTEXBLEND         = 0x00000400
MTL_CALCREFLECTTEXY     = 0x00001000
MTL_PROJECTREFLECTTEXY  = 0x00002000
MTL_PROJECTREFLECTTEXZ  = 0x00004000
MTL_ADDEFFECT           = 0x00008000
MTL_ALPHATEX            = 0x40000000
MTL_COLORKEY            = 0x20000000
MTL_ADDITIVEMIX         = 0x80000000



# ----------------------------------
# Fallbacks / Special Cases
# ----------------------------------
ALPHA_FALLBACK = ["9ker1.bmp"]  # Textures that require legacy alpha mapping fallback


def print_debug(text):
    if bpy.context.preferences.addons['Mafia_Formats'].preferences.debug_logging:
        print(text)
    
class The4DSExporter:
    def __init__(self, filepath, collection):
        self.filepath = filepath
        self.collection = collection
        self.materials = []
        self.objects = []
        self.version = VERSION_MAFIA
        self.frames_map = {}  # Maps Blender objects to frame indices
        self.joint_map = {}   # Maps bone names to joint frame indices
        self.frame_index = 1  # Starts at 1, as in importer
        self.lod_map = {}     # Maps base mesh to LOD objects


    def get_emission_color(self, principled):
        emission_input = principled.inputs["Emission Color"]
        
        if emission_input.is_linked:
            emission_node = emission_input.links[0].from_node

            if isinstance(emission_node, bpy.types.ShaderNodeMixRGB) and emission_node.blend_type == 'MULTIPLY':
                if emission_node.inputs[1].is_linked:
                    mix_node = emission_node.inputs[1].links[0].from_node
                else:
                    mix_node = None
            else:
                mix_node = emission_node

            if isinstance(mix_node, bpy.types.ShaderNodeMixRGB) and mix_node.blend_type == 'MULTIPLY':
                strength_color = mix_node.inputs[1].default_value
                return strength_color[:3]

        color = emission_input.default_value[:3]
        if any(c > 0.0 for c in color):
            return color

        return None


    def serialize_material(self, f, mat, mat_index):
        """Serialize a Blender material to 4DS format."""
        nodes = mat.node_tree.nodes if mat.use_nodes else []
        principled = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)

        flags = 0
        diffuse_tex = ""
        alpha_tex = ""
        env_tex = ""
        metallic = 0.0
        emission = (0.0, 0.0, 0.0)
        alpha = 1.0

        if principled:
            # -- Diffuse texture only from 'Base Color' input
            base_color = principled.inputs["Base Color"]
            if base_color.is_linked:
                tex_node = base_color.links[0].from_node

                if isinstance(tex_node, bpy.types.ShaderNodeTexImage) and tex_node.image:
                    diffuse_tex = tex_node.image.name.upper()
                    flags |= MTL_DIFFUSETEX

                elif isinstance(tex_node, bpy.types.ShaderNodeMixRGB):
                    diffuse_input = tex_node.inputs["Color1"]
                    env_input = tex_node.inputs["Color2"]

                    if diffuse_input.is_linked:
                        diffuse_node = diffuse_input.links[0].from_node
                        if isinstance(diffuse_node, bpy.types.ShaderNodeTexImage) and diffuse_node.image:
                            diffuse_tex = diffuse_node.image.name.upper()
                            flags |= MTL_DIFFUSETEX

                    if env_input.is_linked:
                        env_node = env_input.links[0].from_node
                        if isinstance(env_node, bpy.types.ShaderNodeTexImage) and env_node.image:
                            env_tex = env_node.image.name.upper()
                            flags |= MTL_ENVMAP

                    metallic = principled.inputs["Metallic"].default_value


            # -- Alpha texture or color key from 'Alpha' input
            alpha_input = principled.inputs["Alpha"]
            if alpha_input.is_linked:
                alpha_node = alpha_input.links[0].from_node

                if isinstance(alpha_node, bpy.types.ShaderNodeTexImage) and alpha_node.image:
                    alpha_name = alpha_node.image.name.upper()
                    if "KEYMASK" not in alpha_name:
                        alpha_tex = alpha_name
                        flags |= MTL_ADDEFFECT | MTL_ALPHATEX
                    elif flags & MTL_DIFFUSETEX:
                        # Treat as color key if flagged and KEYMASK detected
                        flags |= MTL_ADDEFFECT | MTL_COLORKEY

                elif isinstance(alpha_node, bpy.types.ShaderNodeMath):
                    if flags & MTL_DIFFUSETEX:
                        flags |= MTL_ADDEFFECT | MTL_COLORKEY
            else:
                alpha = alpha_input.default_value

            # -- Emission

            emission_strength = principled.inputs["Emission Strength"].default_value

            if emission_strength > 0:
                emission = self.get_emission_color(principled) or emission

        # Write core material data
        Util.write_int_32(f, flags)
        Util.write_vector3(f, (1.0, 1.0, 1.0))  # Ambient
        Util.write_vector3(f, (1.0, 1.0, 1.0))  # Diffuse
        Util.write_vector3(f, emission)        # Emission
        Util.write_float_32(f, alpha)          # Opacity

        if flags & MTL_ENVMAP:
            Util.write_float_32(f, metallic)
            Util.write_string(f, env_tex)

        Util.write_string(f, diffuse_tex)

        if flags & MTL_ALPHATEX:
            Util.write_string(f, alpha_tex)


    def serialize_object(self, f, obj, lods):
        """Serialize a mesh object with multiple LODs (Level of Detail), with UV-safe vertex duplication."""
        print(f"[WRITE] serialize_object() starts at {f.tell()}")

        Util.write_int_16(f, 0)  # instanceID = 0 (no instancing)
        Util.write_uint_8(f, len(lods))  # Number of LODs

        for lod_idx, lod_obj in enumerate(lods):
            mesh = lod_obj.data
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            uv_layer = bm.loops.layers.uv.active
            if not uv_layer:
                print(f"[WARN] No UV layer found for {lod_obj.name}, defaulting to (0,0)")
                uv_layer = None

            bmesh.ops.split_edges(bm, edges=bm.edges, use_verts=True)  # Split on seams

            Util.write_float_32(f, 100.0 * (1 + lod_idx))  # clippingRange

            # Build flattened vertex list (per-loop UV split)
            export_verts = []
            export_normals = []
            export_uvs = []
            index_map = {}
            next_index = 0
            face_groups = {}

            for face in bm.faces:
                slot = face.material_index
                face_indices = []

                for loop in [face.loops[0], face.loops[2], face.loops[1]]:  # Flip winding
                    v = loop.vert
                    uv = loop[uv_layer].uv if uv_layer else (0.0, 0.0)
                    key = (v.index, round(uv.x, 6), round(uv.y, 6))

                    if key not in index_map:
                        index_map[key] = next_index
                        export_verts.append(v.co.copy())
                        export_normals.append(v.normal.copy())
                        export_uvs.append((uv.x, -uv.y))  # Flip V
                        next_index += 1

                    face_indices.append(index_map[key])

                face_groups.setdefault(slot, []).append(face_indices)

            # Write vertices
            Util.write_int_16(f, len(export_verts))
            for pos, norm, uv in zip(export_verts, export_normals, export_uvs):
                Util.write_vector3(f, pos, True)
                Util.write_vector3(f, norm, True)
                Util.write_vector2(f, uv)

            # Write face groups
            Util.write_uint_8(f, len(face_groups))
            for mat_idx, faces in face_groups.items():
                Util.write_int_16(f, len(faces))
                for indices in faces:
                    Util.write_face_indices(f, indices)

                # Resolve material
                mat_slot = mat_idx if mat_idx < len(lod_obj.material_slots) else 0
                mat = lod_obj.material_slots[mat_slot].material
                mat_id = self.materials.index(mat) + 1 if mat in self.materials else 0
                Util.write_int_16(f, mat_id)

            bm.free()

        return len(lods)


    def serialize_singlemesh(self, f, obj, num_lods):
        """Serialize SINGLEMESH data for a skinned mesh."""
        armature = next((mod.object for mod in obj.modifiers if mod.type == "ARMATURE"), None)
        if not armature:
            return

        bones = armature.data.bones
        bone_names = {b.name for b in bones}
        total_verts = len(obj.data.vertices)

        for lod_idx in range(num_lods):
            Util.write_uint_8(f, len(bones))  # numBones

            # Build vertex group map
            non_weighted_count = 0
            vertex_to_groups = {}
            for v in obj.data.vertices:
                relevant = [(obj.vertex_groups[g.group].name, g.weight)
                            for g in v.groups
                            if obj.vertex_groups[g.group].name in bone_names and g.weight > 0.0]
                if not relevant:
                    non_weighted_count += 1
                vertex_to_groups[v.index] = relevant

            Util.write_int_32(f, non_weighted_count)

            # Mesh AABB
            coords = [v.co for v in obj.data.vertices]
            min_bounds = Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords)))
            max_bounds = Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords)))

            Util.write_vector3(f, min_bounds, reorder=True)
            Util.write_vector3(f, max_bounds, reorder=True)

            # Track linear vertex layout
            written_vertices = set()
            vertex_order = []

            for bone_idx, bone in enumerate(bones):
                # Mafia expects object-to-bone (inverse bind matrix)
                inverse_bind = (armature.matrix_world @ bone.matrix_local).inverted()
                Util.write_matrix4x4(f, inverse_bind)

                vg = obj.vertex_groups.get(bone.name)
                locked = []
                weighted = []

                if vg:
                    for v in obj.data.vertices:
                        for g in v.groups:
                            if g.group == vg.index:
                                if g.weight == 1.0:
                                    locked.append(v.index)
                                elif 0.0 < g.weight < 1.0:
                                    weighted.append((v.index, g.weight))

                # Mafia assumes implicit vertex ordering
                Util.write_int_32(f, len(locked))
                Util.write_int_32(f, len(weighted))
                Util.write_int_32(f, bone_idx)
                Util.write_vector3(f, min_bounds, reorder=True)
                Util.write_vector3(f, max_bounds, reorder=True)

                for _, weight in weighted:
                    Util.write_float_32(f, weight)

                # Keep linear order for debug/consistency
                vertex_order.extend(locked + [vidx for vidx, _ in weighted])
                written_vertices.update(locked)
                written_vertices.update(vidx for vidx, _ in weighted)

            # (Optional) Sanity check: warn if not all verts were handled
            unprocessed = [i for i in range(total_verts) if i not in written_vertices]
            if unprocessed:
                print_debug(f"[WARN] {len(unprocessed)} vertices not assigned to any bone: {unprocessed}")


    def serialize_morph(self, f, obj, num_lods):
        """Serialize MORPH data for shape keys."""
        shape_keys = obj.data.shape_keys
        if not shape_keys or len(shape_keys.key_blocks) <= 1:
            Util.write_uint_8(f, 0)  # numTargets
            return

        # Group shape keys by [LOD][Channel] → list of (target_idx, key)
        morph_data = {}
        for key in shape_keys.key_blocks[1:]:
            parts = key.name.split("_")
            if len(parts) < 2 or parts[0] != "Target":
                print(f"[WARN] Skipping malformed shape key name '{key.name}'")
                continue

            try:
                target_idx = int(parts[1])
                lod_idx = next((int(p[3:]) for p in parts if p.startswith("LOD")), 0)
                channel_idx = next((int(p[7:]) for p in parts if p.startswith("Channel")), 0)
                if lod_idx < num_lods:
                    morph_data.setdefault(lod_idx, {}).setdefault(channel_idx, []).append((target_idx, key))
            except ValueError:
                print(f"[WARN] Skipping shape key '{key.name}' due to parse error")
                continue

        # Compute counts
        num_targets = max((len(t) for lod in morph_data.values() for t in lod.values()), default=1)
        num_channels = max((len(lod) for lod in morph_data.values()), default=1)

        Util.write_uint_8(f, num_targets)
        Util.write_uint_8(f, num_channels)
        Util.write_uint_8(f, num_lods)

        vertices = obj.data.vertices

        for lod_idx in range(num_lods):
            for channel_idx in range(num_channels):
                targets = morph_data.get(lod_idx, {}).get(channel_idx, [])
                num_vertices = len(vertices)
                Util.write_int_16(f, num_vertices)

                for v_idx in range(num_vertices):
                    for target_id in range(num_targets):
                        key = next((k for t, k in targets if t == target_id), None)
                        pos = key.data[v_idx].co if key else vertices[v_idx].co
                        norm = vertices[v_idx].normal  # Approximation

                        Util.write_vector3(f, pos, reorder=True)
                        Util.write_vector3(f, norm, reorder=True)

                f.write(struct.pack("<?", False))  # unknown: no vertex indices

            # Write bounding box
            coords = [v.co for v in vertices]
            min_bounds = Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords)))
            max_bounds = Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords)))
            center = (min_bounds + max_bounds) / 2
            dist = (max_bounds - min_bounds).length

            Util.write_vector3(f, min_bounds, reorder=True)
            Util.write_vector3(f, max_bounds, reorder=True)
            Util.write_vector3(f, center, reorder=True)
            Util.write_float_32(f, dist)


    def serialize_dummy(self, f, obj):
        """Serialize a DUMMY frame's bounding box (AABB)."""
        min_bounds = Vector(obj.get("bbox_min", (0.0, 0.0, 0.0)))
        max_bounds = Vector(obj.get("bbox_max", (0.0, 0.0, 0.0)))

        Util.write_vector3(f, min_bounds, reorder=True)
        Util.write_vector3(f, max_bounds, reorder=True)


    def serialize_target(self, f, obj):
        """Serialize a TARGET frame (with optional link IDs)."""
        Util.write_int_16(f, 0)  # Unknown field

        link_ids = obj.get("link_ids", [])
        Util.write_uint_8(f, len(link_ids))

        if link_ids:
            Util.write_uint16_array(f, link_ids)


    def serialize_sector(self, f, obj):
        """Serialize a SECTOR frame, including geometry and portal children."""
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        # Write sector flags
        flags = obj.get("flags", [0, 0])
        Util.write_int_32(f, int(flags[0], 16))
        Util.write_int_32(f, int(flags[1], 16))

        # Write vertex and face counts
        Util.write_int_32(f, len(bm.verts))
        Util.write_int_32(f, len(bm.faces))

        # Write vertices (Z-up to Y-up)
        for vert in bm.verts:
            Util.write_vector3(f, vert.co, reorder=True)

        # Write triangle faces
        for face in bm.faces:
            idxs = [v.index for v in face.verts]
            Util.write_face_indices(f, [idxs[0], idxs[2], idxs[1]])

        # Write AABB
        min_bounds = Vector(obj.get("min_bounds", (0.0, 0.0, 0.0)))
        max_bounds = Vector(obj.get("max_bounds", (0.0, 0.0, 0.0)))
        Util.write_vector3(f, min_bounds, reorder=True)
        Util.write_vector3(f, max_bounds, reorder=True)

        # Process portal children
        portal_objs = [child for child in obj.children if "plane" in child and child.type == "MESH"]
        Util.write_uint_8(f, len(portal_objs))

        for portal in portal_objs:
            portal_mesh = portal.data
            bm_portal = bmesh.new()
            bm_portal.from_mesh(portal_mesh)
            bm_portal.verts.ensure_lookup_table()

            Util.write_uint_8(f, len(bm_portal.verts))
            Util.write_float_array(f, portal.get("plane", (0.0, 0.0, 1.0, 0.0)))  # Plane as 4 floats
            Util.write_int_32(f, int(portal.get("flags", "0x0"), 16))
            Util.write_float_32(f, portal.get("near_range", 0.0))
            Util.write_float_32(f, portal.get("far_range", 100.0))

            for vert in bm_portal.verts:
                Util.write_vector3(f, vert.co, reorder=True)

            bm_portal.free()

        bm.free()


    def serialize_occluder(self, f, obj):
        """Serialize an OCCLUDER frame."""
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        Util.write_int_32(f, len(bm.verts))
        Util.write_int_32(f, len(bm.faces))

        for vert in bm.verts:
            Util.write_vector3(f, vert.co, reorder=True)

        for face in bm.faces:
            idxs = [v.index for v in face.verts]
            Util.write_face_indices(f, [idxs[0], idxs[2], idxs[1]])

        bm.free()


    def serialize_frame(self, f, obj):
        """Serialize a single frame (object, dummy, sector, etc.) into 4DS format."""

        # Frame type determination
        frame_type = FRAME_VISUAL
        visual_type = VISUAL_OBJECT
        visual_flags = (0, 0)

        if obj.type == "MESH":
            if any(mod.type == "ARMATURE" for mod in obj.modifiers):
                shape_keys = obj.data.shape_keys
                visual_type = VISUAL_SINGLEMORPH if shape_keys and len(shape_keys.key_blocks) > 1 else VISUAL_SINGLEMESH
            elif "num_portals" in obj or any("plane" in child for child in obj.children):
                frame_type = FRAME_SECTOR
            elif obj.display_type == "WIRE" and "num_portals" not in obj:
                frame_type = FRAME_OCCLUDER
            elif obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 1:
                visual_type = VISUAL_MORPH
        elif obj.type == "EMPTY":
            if obj.empty_display_type == "CUBE":
                frame_type = FRAME_DUMMY
            elif obj.empty_display_type == "PLAIN_AXES":
                frame_type = FRAME_TARGET
        elif obj.type == "ARMATURE":
            return  # Skip armature objects directly

        # Parent frame index
        parent_id = self.frames_map.get(obj.parent, 0)

        # Transform
        matrix = obj.matrix_local if obj.parent else obj.matrix_world
        pos = matrix.to_translation()
        rot = matrix.to_quaternion()
        scale = matrix.to_scale()

        # Store frame index
        self.frames_map[obj] = self.frame_index
        self.frame_index += 1


        # Write header
        Util.write_uint_8(f, frame_type)

        if frame_type == FRAME_VISUAL:
            Util.write_uint_8(f, visual_type)

            Util.write_BB(f, visual_flags)


        Util.write_int_16(f, parent_id)
        Util.write_vector3(f, pos, reorder=True)
        Util.write_vector3(f, scale, reorder=True)

        Util.write_quat(f, rot, reorder=True)

        Util.write_uint_8(f, 0)  # cullingFlags

        Util.write_string(f, obj.name)

        props = obj.get("Frame Properties", "")
        Util.write_string(f, props)

        # Serialize content based on type
        if frame_type == FRAME_VISUAL:
            lods = self.lod_map.get(obj, [obj])
            if visual_type in (VISUAL_OBJECT, VISUAL_LITOBJECT):
                print('Visual_Normal')
                self.serialize_object(f, obj, lods)
            elif visual_type in (VISUAL_SINGLEMESH, VISUAL_SINGLEMORPH):
                num_lods = self.serialize_object(f, obj, lods)
                self.serialize_singlemesh(f, obj, num_lods)
                if visual_type == VISUAL_SINGLEMORPH:
                    self.serialize_morph(f, obj, num_lods)
            elif visual_type == VISUAL_MORPH:
                num_lods = self.serialize_object(f, obj, lods)
                self.serialize_morph(f, obj, num_lods)
        elif frame_type == FRAME_SECTOR:
            self.serialize_sector(f, obj)
        elif frame_type == FRAME_DUMMY:
            self.serialize_dummy(f, obj)
        elif frame_type == FRAME_TARGET:
            self.serialize_target(f, obj)
        elif frame_type == FRAME_OCCLUDER:
            self.serialize_occluder(f, obj)

    def serialize_joint(self, f, bone, armature, matrix):
        matrix = armature.matrix_world.inverted() @ bone.matrix_local

        # Swap Y/Z rows for Y-up coordinate system (manual swap)
        matrix[1], matrix[2] = matrix[2], matrix[1]

        Util.write_matrix4x4(f, matrix)

        bone_idx = list(armature.data.bones).index(bone)
        Util.write_int_32(f, bone_idx)
        

    def serialize_joints(self, f, armature):
        """Serialize each armature bone as a JOINT frame."""

        originalIndex = self.frame_index
        for bone in armature.data.bones:
            self.joint_map[bone.name] = self.frame_index
            self.frame_index += 1

        self.frame_index = originalIndex

        for bone in armature.data.bones:
            frame_type = FRAME_JOINT

            parent_id = (
                self.joint_map.get(bone.parent.name, self.frames_map.get(armature, 0))
                if bone.parent else 0
            )

            # Build matrix and reorder from Blender Z-up to Y-up
            #matrix = armature.matrix_world() @ bone.matrix_local
            matrix = bone.matrix_local

            if bone.parent:
                matrix = bone.parent.matrix_local.inverted() @ bone.matrix_local


            pos = matrix.to_translation()
            rot = matrix.to_quaternion()
            scale = matrix.to_scale()

            # Write frame header
            Util.write_uint_8(f, frame_type)
            Util.write_int_16(f, parent_id)
            Util.write_vector3(f, pos, True)  # already Y-up
            Util.write_vector3(f, scale, True)
            Util.write_quat(f, rot, True)
            Util.write_uint_8(f, 0)  # cullingFlags

            Util.write_string(f, bone.name)
            Util.write_string(f, "")  # Frame properties (unused)

            self.serialize_joint(f, bone, armature, matrix)


    def collect_lods(self):
        """Group mesh LOD objects under their base object, excluding standalone _lodX objects."""
        all_lod_objects = set()

        for obj in self.elements:
            if obj.type != "MESH" or "_lod" not in obj.name.lower():
                continue

            name_parts = obj.name.rsplit("_lod", 1)
            if len(name_parts) != 2 or not name_parts[1].isdigit():
                continue  # Skip malformed names

            base_name, lod_str = name_parts
            lod_num = int(lod_str)

            base_obj = next(
                (o for o in self.elements if o.name == base_name and o.type == "MESH"),
                None
            )
            if not base_obj or lod_num < 1:
                continue  # Skip unlinked or invalid LODs

            all_lod_objects.add(obj)
            if base_obj not in self.lod_map:
                self.lod_map[base_obj] = [base_obj]  # LOD 0 always goes first

            # Ensure list is large enough
            while len(self.lod_map[base_obj]) <= lod_num:
                self.lod_map[base_obj].append(None)

            self.lod_map[base_obj][lod_num] = obj

        # Trim None placeholders
        for base_obj in self.lod_map:
            self.lod_map[base_obj] = [lod for lod in self.lod_map[base_obj] if lod]

        return all_lod_objects


    def buildObjectList(self, elements):
        element_list = []
        for element in elements:
            if not "_Portal" in element.name:
                element_list.append(element)
            elif element.parent:
                parent = element.parent
                if parent not in self.portal_parents:
                    self.portal_parents[parent] = []
                self.portal_parents[parent].append(element)
        return element_list

    def serialize_file(self):
        """Main 4DS file serialization entry point."""
        with open(self.filepath, "wb") as f:
            Util.serialize_header(f, self.version)

            self.portal_parents = {} # Important later on

            self.elements = self.buildObjectList(bpy.context.selected_objects)

            # Collect and write unique materials
            self.materials = list({
                mat for obj in self.elements
                if obj.type == "MESH" and obj.data.materials
                for mat in obj.data.materials if mat
            })

            Util.write_int_16(f, len(self.materials))

            for i, mat in enumerate(self.materials):
                self.serialize_material(f, mat, i + 1)

            # Handle LODs and base object filtering
            lod_objects = self.collect_lods()
            self.objects = [
                obj for obj in self.elements
                if obj.type in {"MESH", "EMPTY"} and obj not in lod_objects
            ]

            armatures = [obj for obj in self.elements if obj.type == "ARMATURE"]

            total_frames = len(self.objects) + sum(len(arm.data.bones) for arm in armatures)

            Util.write_int_16(f, total_frames)

            print(total_frames)
                
            # Serialize normal objects
            for obj in self.objects:
                self.serialize_frame(f, obj)


            # Serialize joints
            for armature in armatures:
                self.frames_map[armature] = self.frame_index
                self.serialize_joints(f, armature)

                
            f.write(struct.pack("<?", False))  # No animation


class Export4DS(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.4ds"
    bl_label = "Export 4DS"
    filename_ext = ".4ds"
    filter_glob = StringProperty(default="*.4ds", options={"HIDDEN"})

    def execute(self, context):
        exporter = The4DSExporter(self.filepath, context.collection)
        exporter.serialize_file()
        return {"FINISHED"}



def menu_func_export(self, context):
    self.layout.operator(Export4DS.bl_idname, text="4DS Model File (.4ds)")

def register():
    bpy.utils.register_class(Export4DS)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    bpy.utils.unregister_class(Export4DS)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)