
######################################## LICENSE #################################################
# This program is free software: you can redistribute it and/or modify it under the terms of the #
# GNU General Public License as published by the Free Software Foundation, either version 3 of   #
# the License, or (at your option) any later version.                                            #
#                                                                                                #
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;      #
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.      #
# See the GNU General Public License for more details.                                           #
#                                                                                                #
# You should have received a copy of the GNU General Public License along with this program. If  #
# not, see <https://www.gnu.org/licenses/>.                                                      #
##################################################################################################

import platform
import time
import numpy as np
import bpy
from collections import defaultdict, deque, namedtuple

OS = platform.system()
bl_info = {
    "name": "Node Orthogonalizer",
    "description": "Automatically routes Blender node links with clean right-angle turns",
    "author": "Andy294753951 (Blender 5.2 rewrite), Kai Christensen (original)",
    "version": (2, 1, 1),
    "blender": (5, 2, 0),
    "doc_url": "https://github.com/Andy294753951/node-orthogonalizer-blender",
    "support": "COMMUNITY",
    "category": "Node",
}


Socket = namedtuple('Socket', ['socket', 'direction', 'x', 'y'])
Point = namedtuple('Point', ['x', 'y'])

# A reroute's RNA location is the top-left of its small drawing box, while
# links attach to the box centre. Treating location as the socket centre was
# the source of the small diagonal segments visible in Blender 5.x.
REROUTE_SIZE = 10.0

bpy.types.Node.is_reroute = bpy.props.BoolProperty(name="Is Reroute Node", default=False)
bpy.types.Node.x_lock = bpy.props.BoolProperty(name="X Lock", default=False)
bpy.types.Node.y_lock = bpy.props.BoolProperty(name="Y Lock", default=False)
bpy.types.NodeSocket.center_offset = bpy.props.FloatProperty(name="Center Offset", default=0)


def get_ui_scaling(context):
    """Return Blender's effective UI scale, including Windows display scale."""
    view_scale = context.preferences.view.ui_scale
    system_scale = context.preferences.system.ui_scale
    return max(float(view_scale) * float(system_scale), 0.01)


def get_undrawn_reroute_size(context):
    """Match the 0.5-pixel inset used by Blender's reroute drawing box."""
    ui_scaling = get_ui_scaling(context)
    return REROUTE_SIZE - (0.5 / ui_scaling)


def get_active_tree(context):
    """Return the tree currently visible in the editor, including nested groups."""
    space = context.space_data
    tree = getattr(space, 'edit_tree', None) or space.node_tree
    path = [
        item.node_tree
        for item in getattr(space, 'path', ())
        if getattr(item, 'node_tree', None) is not None
    ]
    return tree, path


def get_nodes_links(context):
    tree, path = get_active_tree(context)
    return tree.nodes, tree.links


def get_node_location(node):
    """Return a node's top-left location in node-tree coordinates."""
    location = getattr(node, 'location_absolute', node.location)
    return Point(float(location.x), float(location.y))


def set_node_location(node, x, y):
    """Set a node's top-left location in node-tree coordinates."""
    if node.parent is None:
        node.location = (x, y)
        return

    parent_location = get_node_location(node.parent)
    node.location = (x - parent_location.x, y - parent_location.y)


def is_orphan(node):
    sockets = [*node.inputs, *node.outputs]
    linked_status = [x.is_linked for x in sockets]
    return not any(linked_status)

# code for calculating socket positions is taken from a SO post by Markus von Broady


def is_hidden(socket):
    return socket.hide or not socket.enabled


def is_tall(node, socket):
    if socket.type != 'VECTOR':
        return False
    if socket.hide_value:
        return False
    if socket.is_linked:
        return False
    if node.type == 'BSDF_PRINCIPLED' and socket.identifier == 'Subsurface Radius':
        return False  # an exception confirms a rule?
    return True


def assign_output_offsets(node, gap):

    outputs = [n for n in node.outputs if (not n.hide_value) and (n.is_linked)]
    n_out = len(outputs)

    if n_out > 1:
        spread = gap*(n_out-1)
        start = -1*spread/2
        stop = spread/2
        offsets = np.linspace(start=start, stop=stop, num=n_out)
        for offset, output in zip(offsets, outputs):
            output.center_offset = offset


def get_reroute_center(node, context):
    """Return the actual link socket centre of a reroute in node coordinates."""
    ui_scaling = get_ui_scaling(context)
    width = node.dimensions.x
    height = node.dimensions.y

    if OS == 'Darwin':
        width /= 2.0
        height /= 2.0

    fallback_size = get_undrawn_reroute_size(context)
    width = width / ui_scaling if width > 0 else fallback_size
    height = height / ui_scaling if height > 0 else fallback_size
    location = get_node_location(node)
    return Point(location.x + (width / 2.0),
                 location.y - (height / 2.0))


def set_reroute_center(node, x, y, context):
    """Place a reroute so its visible socket centre is exactly at (x, y)."""
    ui_scaling = get_ui_scaling(context)
    width = node.dimensions.x
    height = node.dimensions.y

    if OS == 'Darwin':
        width /= 2.0
        height /= 2.0

    fallback_size = get_undrawn_reroute_size(context)
    width = width / ui_scaling if width > 0 else fallback_size
    height = height / ui_scaling if height > 0 else fallback_size
    set_node_location(node, x - (width / 2.0), y + (height / 2.0))


def align_reroute_center(node, context, x=None, y=None):
    """Move one or both reroute-centre axes without disturbing the other."""
    center = get_reroute_center(node, context)
    set_reroute_center(
        node,
        center.x if x is None else x,
        center.y if y is None else y,
        context,
    )


def get_socket_dict(node, context):
    inputs = list(reversed(node.inputs))
    outputs = node.outputs

    # Empty dict for holding input and output socket coordinates
    socket_dict = {'input': {}, 'output': {}}

    UI_SCALING = get_ui_scaling(context)
    node_location = get_node_location(node)
    node_x = node_location.x
    node_y = node_location.y

    Y_TOP = 38.25

    NORMAL_Y_BOTTOM = 10.25
    NORMAL_HEIGHT = 20.75

    VEC_Y_BOTTOM = 75
    VEC_HEIGHT = 82.5

    if OS == 'Darwin':
        # node.dimensions is mysteriously off by a factor of 2
        node_width = node.dimensions.x / 2
        node_height = node.dimensions.y / 2
    else:
        node_width = node.dimensions.x
        node_height = node.dimensions.y

    # Dimensions are the only reliable height for large node groups and image
    # nodes. They can be zero until the editor has drawn once, so retain RNA
    # width/height as a safe fallback for manual execution during that window.
    if node_width <= 0:
        node_width = node.width
    if node_height <= 0:
        node_height = node.height

    node_width = node_width/UI_SCALING
    node_height = node_height/UI_SCALING

    if (node.bl_idname != 'NodeReroute') and (not node.hide):

        # Walk up the inputs and store their positions (have to account for "tall" inputs)
        x = node_x
        y = node_y - node_height
        counter = 0
        for i in inputs:

            if is_hidden(i):
                continue

            tall = is_tall(node, i)

            if (counter == 0) and (tall):
                y += VEC_Y_BOTTOM
            if (counter == 0) and (not tall):
                y += NORMAL_Y_BOTTOM
            if (counter != 0) and (tall):
                y += VEC_HEIGHT
            if (counter != 0) and (not tall):
                y += NORMAL_HEIGHT

            socket_dict['input'][i.identifier] = Socket(i, 'input', x, y)
            counter += 1

        # Blender 5.x draws the first Principled BSDF inputs above a set of
        # collapsed panels. The RNA socket list still contains every panel
        # socket, so the legacy bottom-up walk places Base Color far too low.
        # These are the seven sockets that are visibly laid out above those
        # panels in Blender 5.2.
        if node.bl_idname == 'ShaderNodeBsdfPrincipled' and bpy.app.version >= (5, 0, 0):
            visible_principled_inputs = {
                'Base Color': 0,
                'Metallic': 1,
                'Roughness': 2,
                'IOR': 3,
                'Alpha': 4,
                'Thin Wall': 5,
                'Normal': 6,
            }
            for identifier, row in visible_principled_inputs.items():
                socket = node.inputs.get(identifier)
                if socket is not None and not is_hidden(socket):
                    socket_dict['input'][socket.identifier] = Socket(
                        socket,
                        'input',
                        node_x,
                        node_y - 59.0 - (row * 21.33),
                    )

        # These expanded vector controls have node-specific padding in 5.x.
        # Measuring from the top avoids accumulating the different control
        # heights that appear below them.
        if node.bl_idname == 'ShaderNodeMapping' and bpy.app.version >= (5, 0, 0):
            socket = node.inputs.get('Vector')
            if socket is not None and not is_hidden(socket):
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node_x,
                    node_y - 85.25,
                )

        if node.bl_idname == 'ShaderNodeTexNoise' and bpy.app.version >= (5, 0, 0):
            socket = node.inputs.get('Vector')
            if socket is not None and not is_hidden(socket):
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node_x,
                    node_y - 154.5,
                )

        # Material Output has a target selector above its inputs in Blender
        # 5.x, so its sockets are best measured from the node top.
        if node.bl_idname == 'ShaderNodeOutputMaterial' and bpy.app.version >= (5, 0, 0):
            for row, socket in enumerate(node.inputs):
                if not is_hidden(socket):
                    socket_dict['input'][socket.identifier] = Socket(
                        socket,
                        'input',
                        node_x,
                        node_y - 61.0 - (row * NORMAL_HEIGHT),
                    )

        # Group nodes draw outputs first, followed by the node-group selector,
        # then their inputs. Walking upward from the bottom accumulates errors
        # on large groups such as MMDShaderDev, so measure linked rows from the
        # top instead.
        if node.bl_idname == 'ShaderNodeGroup' and bpy.app.version >= (5, 0, 0):
            visible_outputs = [socket for socket in node.outputs if not is_hidden(socket)]
            visible_inputs = [socket for socket in node.inputs if not is_hidden(socket)]
            first_input_offset = Y_TOP + (len(visible_outputs) * NORMAL_HEIGHT) + 26.33
            for row, socket in enumerate(visible_inputs):
                row_offset = row * NORMAL_HEIGHT
                if node.node_tree and node.node_tree.name.startswith('MMDShaderDev'):
                    # mmd_tools deliberately switches to a slightly tighter
                    # layout after Sphere Tex Fac. These values were measured
                    # from Blender 5.2's rendered socket centres.
                    first_input_offset = 126.8236
                    row_offset = (
                        min(row, 8) * 21.33144
                        + max(row - 8, 0) * 20.67212
                    )
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node_x,
                    node_y - first_input_offset - row_offset,
                )

        # Blender 5.2 compositor nodes place their input sockets directly
        # below the header, even when large option panels make the node much
        # taller. The legacy bottom-up walk therefore fails badly for nodes
        # such as Blur and Glare.
        if node.bl_idname.startswith('CompositorNode') and bpy.app.version >= (5, 2, 0):
            visible_inputs = [socket for socket in node.inputs if not is_hidden(socket)]
            for row, socket in enumerate(visible_inputs):
                socket_dict['input'][socket.identifier] = Socket(
                    socket,
                    'input',
                    node_x,
                    node_y - Y_TOP - (row * NORMAL_HEIGHT),
                )

        # Walk down the outputs and store their positions
        x = node_x + node_width - 1.0
        y = node_y

        counter = 0
        for o in outputs:
            if is_hidden(o):
                continue

            if counter == 0:
                y -= Y_TOP
            if counter != 0:
                y -= NORMAL_HEIGHT

            socket_dict['output'][o.identifier] = Socket(o, 'output', x, y)
            counter += 1

        # Bake draws mode and action controls between its header and dynamic
        # item sockets. Each visible output shares a row with its matching
        # input, so reuse the already-correct bottom-up input coordinate. The
        # normal top-down output walk otherwise places every output above its
        # rendered socket in Blender 5.x.
        if node.bl_idname == 'GeometryNodeBake' and bpy.app.version >= (5, 0, 0):
            visible_inputs = [
                socket for socket in node.inputs
                if socket.identifier in socket_dict['input']
            ]
            visible_outputs = [
                socket for socket in node.outputs
                if socket.identifier in socket_dict['output']
            ]
            for input_socket, output_socket in zip(visible_inputs, visible_outputs):
                input_info = socket_dict['input'][input_socket.identifier]
                socket_dict['output'][output_socket.identifier] = Socket(
                    output_socket,
                    'output',
                    x,
                    input_info.y,
                )

    # For when the node is collapsed with sockets arranged in a semicircle at either end
    if (node.bl_idname != 'NodeReroute') and (node.hide):

        Y_CENTER_OFFSET = 10.0

        radius = node_height/2
        input_circle_center = Point(node_x + radius, node_y - Y_CENTER_OFFSET)
        output_circle_center = Point(node_x + node_width - radius, node_y - Y_CENTER_OFFSET)

        visible_inputs = [i for i in inputs if not is_hidden(i)]
        n_in = len(visible_inputs)
        slice_angle = np.pi/(n_in+1)
        for idx, i in enumerate(visible_inputs):

            slice = idx+1
            start = 3*np.pi/2
            x = input_circle_center.x + (np.cos(start-(slice*slice_angle))*radius)
            y = input_circle_center.y + (np.sin(start-(slice*slice_angle))*radius)

            socket_dict['input'][i.identifier] = Socket(i, 'input', x, y)

        visible_outputs = [o for o in outputs if not is_hidden(o)]
        n_out = len(visible_outputs)
        slice_angle = np.pi/(n_out+1)
        for idx, o in enumerate(visible_outputs):

            slice = idx+1
            start = np.pi/2
            x = output_circle_center.x + (np.cos(start-(slice*slice_angle))*radius)
            y = output_circle_center.y + (np.sin(start-(slice*slice_angle))*radius)

            socket_dict['output'][o.identifier] = Socket(o, 'output', x, y)

    if node.bl_idname == 'NodeReroute':
        x, y = get_reroute_center(node, context)
        for i in node.inputs:
            socket_dict['input'][i.identifier] = Socket(i, 'input', x, y)
        for o in node.outputs:
            socket_dict['output'][o.identifier] = Socket(o, 'output', x, y)

    return socket_dict


def check_aligned(socket_1, socket_2, tolerance):
    x1, y1 = (socket_1.x, socket_1.y)
    x2, y2 = (socket_2.x, socket_2.y)
    return (abs(x1 - x2) < tolerance) or (abs(y1 - y2) < tolerance)


def _connected_socket_info(root_direction, link, socket_dict):
    if root_direction == 'input':
        node = link.from_node
        direction = 'output'
        socket = link.from_socket
    else:
        node = link.to_node
        direction = 'input'
        socket = link.to_socket

    return socket_dict.get(node.name, {}).get(direction, {}).get(socket.identifier)


def _nudge_existing_reroutes(valid_nodes, socket_dict, context, nudge_limit):
    """Conservatively align existing reroutes without repeatedly scanning the tree."""
    moved_nodes = set()

    for root_node in valid_nodes:
        if not root_node.is_reroute:
            continue

        targets = []
        root_dict = socket_dict[root_node.name]
        for direction in ('input', 'output'):
            for root_info in root_dict[direction].values():
                if not root_info.socket.is_linked:
                    continue
                for link in list(root_info.socket.links):
                    target = _connected_socket_info(direction, link, socket_dict)
                    if target is not None and target.socket.node != root_node:
                        targets.append(target)

        if not targets:
            continue

        center = get_reroute_center(root_node, context)
        non_reroute_targets = [
            target for target in targets if not target.socket.node.is_reroute
        ]
        if non_reroute_targets and not root_node.y_lock:
            closest = min(
                non_reroute_targets,
                key=lambda target: (
                    (target.x - center.x) ** 2 + (target.y - center.y) ** 2
                ),
            )
            if abs(center.y - closest.y) < nudge_limit:
                align_reroute_center(root_node, context, y=closest.y)
                root_node.y_lock = True
                moved_nodes.add(root_node.as_pointer())
                center = get_reroute_center(root_node, context)

        reroute_targets = [
            target for target in targets if target.socket.node.is_reroute
        ]
        reroute_targets.sort(
            key=lambda target: (
                (target.x - center.x) ** 2 + (target.y - center.y) ** 2
            )
        )
        for target in reroute_targets:
            target_node = target.socket.node
            target_center = get_reroute_center(target_node, context)
            x_distance = target_center.x - center.x
            y_distance = target_center.y - center.y
            axes = sorted(
                (('x', abs(x_distance)), ('y', abs(y_distance))),
                key=lambda item: item[1],
            )
            for axis, distance in axes:
                if distance >= nudge_limit:
                    continue
                if axis == 'x' and not root_node.x_lock:
                    align_reroute_center(root_node, context, x=target_center.x)
                    root_node.x_lock = True
                    target_node.x_lock = True
                elif axis == 'y' and not root_node.y_lock:
                    align_reroute_center(root_node, context, y=target_center.y)
                    root_node.y_lock = True
                    target_node.y_lock = True
                else:
                    continue
                moved_nodes.add(root_node.as_pointer())
                center = get_reroute_center(root_node, context)
                break

            if root_node.x_lock and root_node.y_lock:
                break

    return len(moved_nodes)


def orthogonalize_tree(tree, context, auto_all, tolerance, nudge_limit, noodle_margin):
    """Route each affected link once and return operation statistics."""
    nodes = tree.nodes
    links = tree.links
    original_nodes = list(nodes)
    valid_nodes = [
        node for node in original_nodes
        if (auto_all or node.select) and not is_orphan(node)
    ]
    if not valid_nodes:
        return None

    for node in original_nodes:
        node.is_reroute = node.bl_idname == 'NodeReroute'
        node.x_lock = not node.is_reroute
        node.y_lock = not node.is_reroute
        assign_output_offsets(node, noodle_margin)

    socket_dict = {
        node.name: get_socket_dict(node, context)
        for node in original_nodes
    }
    moved = _nudge_existing_reroutes(
        valid_nodes,
        socket_dict,
        context,
        nudge_limit,
    )

    # Existing reroutes may have moved. Refresh once, then process every
    # original link exactly once. The old implementation rebuilt every socket
    # coordinate table once per node, which became quadratic on large groups.
    socket_dict = {
        node.name: get_socket_dict(node, context)
        for node in original_nodes
    }
    valid_node_ids = {node.as_pointer() for node in valid_nodes}
    original_links = list(links)
    routed = 0

    for link in original_links:
        if not auto_all and not (
            link.from_node.as_pointer() in valid_node_ids
            or link.to_node.as_pointer() in valid_node_ids
        ):
            continue

        source_info = socket_dict.get(link.from_node.name, {}).get('output', {}).get(
            link.from_socket.identifier
        )
        target_info = socket_dict.get(link.to_node.name, {}).get('input', {}).get(
            link.to_socket.identifier
        )
        if source_info is None or target_info is None:
            continue
        if check_aligned(source_info, target_info, tolerance):
            continue

        source_node = link.from_node
        target_node = link.to_node
        source_socket = link.from_socket
        target_socket = link.to_socket
        source_x, source_y = source_info.x, source_info.y
        target_x, target_y = target_info.x, target_info.y
        source_is_reroute = source_node.is_reroute
        target_is_reroute = target_node.is_reroute

        links.remove(link)

        if not source_is_reroute and not target_is_reroute:
            middle_x = (
                ((source_x + target_x) / 2.0)
                + source_socket.center_offset
            )
            first = nodes.new('NodeReroute')
            set_reroute_center(first, middle_x, source_y, context)
            second = nodes.new('NodeReroute')
            set_reroute_center(second, middle_x, target_y, context)
            links.new(source_socket, first.inputs[0])
            links.new(first.outputs[0], second.inputs[0])
            links.new(second.outputs[0], target_socket)
        else:
            corner_x = target_x
            corner_y = source_y
            if source_is_reroute and not target_is_reroute:
                corner_x = source_x
                corner_y = target_y

            corner = nodes.new('NodeReroute')
            set_reroute_center(corner, corner_x, corner_y, context)
            links.new(source_socket, corner.inputs[0])
            links.new(corner.outputs[0], target_socket)

        routed += 1

    return {
        'nodes': len(valid_nodes),
        'moved_reroutes': moved,
        'routed_links': routed,
    }


def _node_size(node):
    """Return a usable node size even before Blender has drawn the editor."""
    width = float(node.dimensions.x)
    height = float(node.dimensions.y)
    if width <= 1.0:
        width = max(float(node.width), 80.0)
    if height <= 1.0:
        height = 40.0 if node.hide else 120.0
    return width, height


def _layout_location(node, parent):
    """Use frame-local coordinates so moving children cannot drag their frame."""
    if parent is None:
        return get_node_location(node)
    return Point(float(node.location.x), float(node.location.y))


def _set_layout_location(node, parent, x, y):
    if parent is None:
        set_node_location(node, x, y)
    else:
        node.location = (x, y)


def _semantic_edges(tree):
    """Collapse reroute chains into source-to-destination graph edges."""
    outgoing = defaultdict(list)
    for link in tree.links:
        outgoing[link.from_node].append(link.to_node)

    source_nodes = [
        node for node in tree.nodes
        if node.bl_idname != 'NodeReroute' and node.type != 'FRAME'
    ]
    edges = set()
    for source in source_nodes:
        queue = deque(outgoing.get(source, ()))
        seen_reroutes = set()
        while queue:
            target = queue.popleft()
            if target.bl_idname == 'NodeReroute':
                pointer = target.as_pointer()
                if pointer in seen_reroutes:
                    continue
                seen_reroutes.add(pointer)
                queue.extend(outgoing.get(target, ()))
                continue
            if target.type != 'FRAME' and target != source:
                edges.add((source, target))
    return edges


def _strongly_connected_components(nodes, successors):
    """Tarjan SCC keeps cyclic node graphs safe and deterministic."""
    index = 0
    indices = {}
    lowlinks = {}
    stack = []
    on_stack = set()
    components = []

    def visit(node):
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in successors[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return

        component = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        components.append(component)

    for node in nodes:
        if node not in indices:
            visit(node)
    return components


def _layer_graph(nodes, edges, positions):
    """Return dependency layers and a low-crossing vertical order."""
    successors = {node: set() for node in nodes}
    predecessors = {node: set() for node in nodes}
    for source, target in edges:
        successors[source].add(target)
        predecessors[target].add(source)

    components = _strongly_connected_components(nodes, successors)
    component_for = {
        node: component_index
        for component_index, component in enumerate(components)
        for node in component
    }
    component_successors = {index: set() for index in range(len(components))}
    indegree = {index: 0 for index in range(len(components))}
    for source, target in edges:
        source_component = component_for[source]
        target_component = component_for[target]
        if source_component == target_component:
            continue
        if target_component not in component_successors[source_component]:
            component_successors[source_component].add(target_component)
            indegree[target_component] += 1

    def component_sort_key(component_index):
        component = components[component_index]
        return min(positions[node].x for node in component)

    ready = sorted(
        (index for index, degree in indegree.items() if degree == 0),
        key=component_sort_key,
    )
    component_layers = {index: 0 for index in range(len(components))}
    topological_order = []
    while ready:
        component_index = ready.pop(0)
        topological_order.append(component_index)
        for target in sorted(
            component_successors[component_index],
            key=component_sort_key,
        ):
            component_layers[target] = max(
                component_layers[target],
                component_layers[component_index] + 1,
            )
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=component_sort_key)

    layers = defaultdict(list)
    for node in nodes:
        layers[component_layers[component_for[node]]].append(node)

    maximum_layer = max(layers, default=0)
    for node in nodes:
        if node.bl_idname == 'NodeGroupInput':
            old_layer = component_layers[component_for[node]]
            if old_layer != 0:
                layers[old_layer].remove(node)
                layers[0].append(node)
        elif node.bl_idname == 'NodeGroupOutput':
            old_layer = component_layers[component_for[node]]
            output_layer = maximum_layer + 1
            if old_layer != output_layer:
                layers[old_layer].remove(node)
                layers[output_layer].append(node)

    layers = {layer: members for layer, members in layers.items() if members}
    for members in layers.values():
        members.sort(key=lambda node: (-positions[node].y, node.name))

    # Alternating barycentre sweeps reduce crossings without an expensive
    # global optimizer. Four passes are enough for large production groups.
    for _ in range(4):
        order_index = {
            node: index
            for layer in sorted(layers)
            for index, node in enumerate(layers[layer])
        }
        for layer in sorted(layers):
            if layer == min(layers):
                continue
            members = layers[layer]
            members.sort(key=lambda node: (
                sum(order_index[p] for p in predecessors[node]) /
                len(predecessors[node]) if predecessors[node] else order_index[node],
                order_index[node],
            ))

        order_index = {
            node: index
            for layer in sorted(layers)
            for index, node in enumerate(layers[layer])
        }
        for layer in sorted(layers, reverse=True):
            if layer == max(layers):
                continue
            members = layers[layer]
            members.sort(key=lambda node: (
                sum(order_index[s] for s in successors[node]) /
                len(successors[node]) if successors[node] else order_index[node],
                order_index[node],
            ))

    return layers, successors, predecessors


def _capture_route_constraints(tree, context):
    """Remember whether each routed segment was horizontal or vertical."""
    if context is None:
        return None
    try:
        socket_dict = {
            node.name: get_socket_dict(node, context)
            for node in tree.nodes
        }
    except (AttributeError, ReferenceError, RuntimeError):
        return None

    constraints = []
    for link in tree.links:
        if (
            link.from_node.bl_idname != 'NodeReroute'
            and link.to_node.bl_idname != 'NodeReroute'
        ):
            continue
        source = socket_dict.get(link.from_node.name, {}).get('output', {}).get(
            link.from_socket.identifier
        )
        target = socket_dict.get(link.to_node.name, {}).get('input', {}).get(
            link.to_socket.identifier
        )
        if source is None or target is None:
            continue
        axis = 'x' if abs(source.x - target.x) <= abs(source.y - target.y) else 'y'
        constraints.append((
            axis,
            link.from_node,
            link.from_socket.identifier,
            link.to_node,
            link.to_socket.identifier,
        ))
    return constraints


def _restore_route_constraints(tree, context, constraints, affected_nodes=None):
    """Move existing reroutes to retain their original axis-aligned segments."""
    if not constraints or context is None:
        return 0
    try:
        socket_dict = {
            node.name: get_socket_dict(node, context)
            for node in tree.nodes
        }
    except (AttributeError, ReferenceError, RuntimeError):
        return 0

    targets = {'x': {}, 'y': {}}
    for axis in ('x', 'y'):
        axis_constraints = [item for item in constraints if item[0] == axis]
        adjacency = defaultdict(set)
        constraint_for_node = defaultdict(list)
        for item in axis_constraints:
            _, source_node, _, target_node, _ = item
            adjacency[source_node].add(target_node)
            adjacency[target_node].add(source_node)
            constraint_for_node[source_node].append(item)
            constraint_for_node[target_node].append(item)

        visited = set()
        for start in adjacency:
            if start in visited:
                continue
            queue = [start]
            visited.add(start)
            component = []
            while queue:
                node = queue.pop()
                component.append(node)
                for neighbour in adjacency[node]:
                    if neighbour not in visited:
                        visited.add(neighbour)
                        queue.append(neighbour)

            reroutes = [
                node for node in component
                if node.bl_idname == 'NodeReroute'
            ]
            if not reroutes:
                continue
            if affected_nodes is not None and not any(
                node in affected_nodes for node in component
            ):
                continue

            fixed_values = []
            for item in {
                item for node in component for item in constraint_for_node[node]
            }:
                _, source_node, source_identifier, target_node, target_identifier = item
                source = socket_dict.get(source_node.name, {}).get('output', {}).get(
                    source_identifier
                )
                target = socket_dict.get(target_node.name, {}).get('input', {}).get(
                    target_identifier
                )
                if source is not None and source_node.bl_idname != 'NodeReroute':
                    fixed_values.append(getattr(source, axis))
                if target is not None and target_node.bl_idname != 'NodeReroute':
                    fixed_values.append(getattr(target, axis))

            if not fixed_values:
                continue
            target_value = sum(fixed_values) / len(fixed_values)
            for reroute in reroutes:
                targets[axis][reroute] = target_value

    moved = 0
    for node in set(targets['x']) | set(targets['y']):
        centre = get_reroute_center(node, context)
        target_x = targets['x'].get(node, centre.x)
        target_y = targets['y'].get(node, centre.y)
        if abs(centre.x - target_x) > 0.01 or abs(centre.y - target_y) > 0.01:
            set_reroute_center(node, target_x, target_y, context)
            moved += 1
    return moved


def layout_node_tree(tree, layout_mode, horizontal_gap, vertical_gap, context=None):
    """Arrange selected nodes, or the whole tree, within frame boundaries."""
    route_constraints = _capture_route_constraints(tree, context)
    eligible = [
        node for node in tree.nodes
        if node.bl_idname != 'NodeReroute' and node.type != 'FRAME'
    ]
    selected_frames = [
        node for node in tree.nodes
        if node.type == 'FRAME' and node.select
    ]

    def is_inside_selected_frame(node):
        parent = node.parent
        while parent is not None:
            if parent in selected_frames:
                return True
            parent = parent.parent
        return False

    selected = [
        node for node in eligible
        if node.select or is_inside_selected_frame(node)
    ]
    selected_scope = len(selected) >= 2
    if selected_scope:
        candidates = selected
    elif any(node.type == 'FRAME' for node in tree.nodes):
        # A complex framed graph is usually hand-authored. Requiring a
        # selection prevents one click from scattering every module.
        return None
    else:
        candidates = eligible
    if len(candidates) < 2:
        return None

    semantic_edges = _semantic_edges(tree)
    buckets = defaultdict(list)
    for node in candidates:
        buckets[node.parent].append(node)

    moved = 0
    moved_nodes = set()
    laid_out = 0
    for parent, bucket in buckets.items():
        bucket_set = set(bucket)
        edges = {
            (source, target)
            for source, target in semantic_edges
            if source in bucket_set and target in bucket_set
        }
        connected = {
            node for edge in edges for node in edge
        }
        if len(connected) < 2:
            continue

        ordered_nodes = sorted(connected, key=lambda node: node.name)
        positions = {
            node: _layout_location(node, parent)
            for node in ordered_nodes
        }
        sizes = {node: _node_size(node) for node in ordered_nodes}
        layers, successors, predecessors = _layer_graph(
            ordered_nodes,
            edges,
            positions,
        )

        layer_gap = horizontal_gap
        row_gap = vertical_gap
        if layout_mode == 'COMPACT':
            layer_gap = max(50.0, horizontal_gap * 0.65)
            row_gap = max(20.0, vertical_gap * 0.65)

        start_x = min(positions[node].x for node in ordered_nodes)
        x_for_layer = {}
        cursor_x = start_x
        for layer in sorted(layers):
            x_for_layer[layer] = cursor_x
            cursor_x += max(sizes[node][0] for node in layers[layer]) + layer_gap

        original_centres = {
            node: positions[node].y - (sizes[node][1] / 2.0)
            for node in ordered_nodes
        }
        global_centre = sum(original_centres.values()) / len(original_centres)

        for layer in sorted(layers):
            members = layers[layer]
            if layout_mode == 'COMPACT':
                desired_centres = []
                for node in members:
                    neighbours = predecessors[node] | successors[node]
                    desired_centres.append(
                        sum(original_centres[n] for n in neighbours) / len(neighbours)
                        if neighbours else original_centres[node]
                    )
                layer_centre = sum(desired_centres) / len(desired_centres)
            else:
                layer_centre = global_centre

            total_height = (
                sum(sizes[node][1] for node in members)
                + row_gap * max(len(members) - 1, 0)
            )
            cursor_y = layer_centre + (total_height / 2.0)
            for node in members:
                target_x = x_for_layer[layer]
                target_y = cursor_y
                old = positions[node]
                if abs(old.x - target_x) > 0.01 or abs(old.y - target_y) > 0.01:
                    _set_layout_location(node, parent, target_x, target_y)
                    moved += 1
                    moved_nodes.add(node)
                cursor_y -= sizes[node][1] + row_gap
                laid_out += 1

    if laid_out == 0:
        return None
    moved_reroutes = _restore_route_constraints(
        tree,
        context,
        route_constraints,
        moved_nodes,
    )
    return {
        'nodes': laid_out,
        'moved': moved,
        'moved_reroutes': moved_reroutes,
        'selected_scope': selected_scope,
    }


def _semantic_neighbours(tree, io_node, downstream):
    edges = _semantic_edges(tree)
    if downstream:
        return [target for source, target in edges if source == io_node]
    return [source for source, target in edges if target == io_node]


def optimize_group_io(tree, horizontal_margin, vertical_gap, context=None):
    """Place Group Input/Output close to their actual semantic neighbours."""
    route_constraints = _capture_route_constraints(tree, context)
    proposals = {'INPUT': [], 'OUTPUT': []}
    for node in tree.nodes:
        if node.bl_idname not in {'NodeGroupInput', 'NodeGroupOutput'}:
            continue

        is_input = node.bl_idname == 'NodeGroupInput'
        neighbours = _semantic_neighbours(tree, node, is_input)
        if not neighbours:
            continue

        width, height = _node_size(node)
        neighbour_locations = [get_node_location(other) for other in neighbours]
        neighbour_sizes = [_node_size(other) for other in neighbours]
        neighbour_centres = [
            location.y - (size[1] / 2.0)
            for location, size in zip(neighbour_locations, neighbour_sizes)
        ]
        target_y = sum(neighbour_centres) / len(neighbour_centres) + height / 2.0
        if is_input:
            target_x = min(location.x for location in neighbour_locations)
            target_x -= horizontal_margin + width
            side = 'INPUT'
        else:
            target_x = max(
                location.x + size[0]
                for location, size in zip(neighbour_locations, neighbour_sizes)
            ) + horizontal_margin
            side = 'OUTPUT'
        proposals[side].append([node, target_x, target_y, width, height])

    moved = 0
    moved_nodes = set()
    for side_proposals in proposals.values():
        side_proposals.sort(key=lambda item: item[2], reverse=True)
        previous_bottom = None
        for node, target_x, target_y, width, height in side_proposals:
            if previous_bottom is not None:
                target_y = min(target_y, previous_bottom - vertical_gap)
            old = get_node_location(node)
            if abs(old.x - target_x) > 0.01 or abs(old.y - target_y) > 0.01:
                set_node_location(node, target_x, target_y)
                moved += 1
                moved_nodes.add(node)
            previous_bottom = target_y - height

    total = sum(len(items) for items in proposals.values())
    if total == 0:
        return None
    moved_reroutes = _restore_route_constraints(
        tree,
        context,
        route_constraints,
        moved_nodes,
    )
    return {
        'nodes': total,
        'moved': moved,
        'moved_reroutes': moved_reroutes,
    }


def _remember_manual_layout(tree):
    """Prevent the automatic timer from immediately reprocessing a manual layout."""
    try:
        _auto_state[tree.as_pointer()] = {
            'signature': _tree_signature(tree),
            'changed_at': time.monotonic(),
            'dirty': False,
            'layout_ready': _tree_layout_ready(tree),
        }
    except (NameError, ReferenceError):
        pass


class NODE_OT_orthogonalize(bpy.types.Operator):

    # Metadata class variables used by Blender to construct the operator's F3 menu button
    bl_idname = "node.orthogonalize"
    bl_label = "Node Orthogonalize"
    bl_description = \
        "Forces all non-locked noodles connect to selected nodes to be \
        straight lines with right-angle connections where necessary"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: bpy.props.FloatProperty(name="Tolerance",
                                       description="How off-axis a noodle must be before it is operated on.",
                                       default=5.0,
                                       min=1.0,
                                       max=25.0)
    nudge_limit: bpy.props.FloatProperty(name="Nudge Limit",
                                         description="Maximum distance existing reroute nodes will be nudged to try to align them before adding new reroute nodes.",
                                         default=100.0,
                                         min=0.0,
                                         max=200)
    noodle_margin: bpy.props.FloatProperty(name="Noodle Margin",
                                           description="Distance which overlapping noodles from different node outputs will hopefully be separated by.",
                                           default=20,
                                           min=0,
                                           max=100)
    auto_all: bpy.props.BoolProperty(
        name="Automatic All Nodes",
        description="Internal flag used by automatic mode to process all linked nodes",
        default=False,
        options={'HIDDEN'},
    )
    automatic: bpy.props.BoolProperty(
        name="Automatic Invocation",
        description="Internal flag used to keep automatic edits lightweight",
        default=False,
        options={'HIDDEN'},
    )

    # The poll classmethod is called by Blender to determine whether the operator can be used in a given context. In our case,
    # we don't want it to be possible to use the operator outside of a Node Editor because we'd get an error if we tried that.
    @classmethod
    def poll(cls, context):
        space_data = context.space_data
        status = (space_data.type == 'NODE_EDITOR') and (space_data.node_tree is not None)
        return status

    # The function that's run when you click on the operator in the menu.
    def execute(self, context):
        snapping_on = context.tool_settings.use_snap_node
        if snapping_on:
            context.tool_settings.use_snap_node = False
        try:
            tree, _ = get_active_tree(context)
            stats = orthogonalize_tree(
                tree,
                context,
                self.auto_all,
                self.tolerance,
                0.0 if self.automatic else self.nudge_limit,
                self.noodle_margin,
            )
            if stats is None:
                return {'CANCELLED'}
            return {'FINISHED'}
        finally:
            context.tool_settings.use_snap_node = snapping_on


class NODE_OT_tree_layout(bpy.types.Operator):
    bl_idname = "node.orthogonalizer_tree_layout"
    bl_label = "Organize Node Tree"
    bl_description = (
        "Arrange selected connected nodes as a dependency tree; when fewer "
        "than two nodes are selected, arrange the active tree"
    )
    bl_options = {'REGISTER', 'UNDO'}

    layout_mode: bpy.props.EnumProperty(
        name="Layout",
        description="Choose a clear tree or a shorter-link compact layout",
        items=(
            ('TREE', "Tree", "Clear left-to-right dependency columns"),
            ('COMPACT', "Compact", "Keep dependency columns closer to linked nodes"),
        ),
        default='TREE',
    )
    horizontal_gap: bpy.props.FloatProperty(
        name="Column Gap",
        description="Horizontal space between dependency columns",
        default=140.0,
        min=40.0,
        max=600.0,
    )
    vertical_gap: bpy.props.FloatProperty(
        name="Row Gap",
        description="Vertical space between nodes in one column",
        default=60.0,
        min=10.0,
        max=300.0,
    )
    route_after: bpy.props.BoolProperty(
        name="Create 90-Degree Routes",
        description="Orthogonalize links after arranging; disabled by default for large groups",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space.type == 'NODE_EDITOR' and space.node_tree is not None

    def execute(self, context):
        tree, _ = get_active_tree(context)
        snapping_on = context.tool_settings.use_snap_node
        if snapping_on:
            context.tool_settings.use_snap_node = False
        try:
            stats = layout_node_tree(
                tree,
                self.layout_mode,
                self.horizontal_gap,
                self.vertical_gap,
                context,
            )
            if stats is None:
                self.report(
                    {'WARNING'},
                    "Select connected nodes or a frame before organizing this complex tree",
                )
                return {'CANCELLED'}

            routed = 0
            if self.route_after:
                route_stats = orthogonalize_tree(
                    tree,
                    context,
                    not stats['selected_scope'],
                    5.0,
                    0.0,
                    20.0,
                )
                if route_stats:
                    routed = route_stats['routed_links']
            _remember_manual_layout(tree)
            self.report(
                {'INFO'},
                f"Organized {stats['nodes']} nodes; routed {routed} links",
            )
            return {'FINISHED'}
        finally:
            context.tool_settings.use_snap_node = snapping_on


class NODE_OT_optimize_group_io(bpy.types.Operator):
    bl_idname = "node.orthogonalizer_group_io"
    bl_label = "Optimize Group Input / Output"
    bl_description = (
        "Move Group Input and Group Output beside the nodes they actually serve"
    )
    bl_options = {'REGISTER', 'UNDO'}

    horizontal_margin: bpy.props.FloatProperty(
        name="Link Margin",
        description="Space between group interface nodes and their neighbours",
        default=180.0,
        min=40.0,
        max=800.0,
    )
    vertical_gap: bpy.props.FloatProperty(
        name="I/O Gap",
        description="Minimum gap when multiple group interface nodes exist",
        default=80.0,
        min=10.0,
        max=400.0,
    )

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space.type == 'NODE_EDITOR' and space.node_tree is not None

    def execute(self, context):
        tree, _ = get_active_tree(context)
        stats = optimize_group_io(
            tree,
            self.horizontal_margin,
            self.vertical_gap,
            context,
        )
        if stats is None:
            self.report({'WARNING'}, "This tree has no linked Group Input or Output")
            return {'CANCELLED'}
        _remember_manual_layout(tree)
        self.report({'INFO'}, f"Optimized {stats['nodes']} group interface nodes")
        return {'FINISHED'}


class NODE_PT_orthogonalizer_tools(bpy.types.Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Orthogonalizer"
    bl_label = "Node Orthogonalizer"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space.type == 'NODE_EDITOR'

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        if (
            getattr(space, 'edit_tree', None) is None
            and getattr(space, 'node_tree', None) is None
        ):
            layout.label(text="No active node tree")
            layout.label(text="Open a material, compositor, or geometry tree")
            return

        column = layout.column(align=True)
        column.label(text="Organize Layout")
        operator = column.operator(
            NODE_OT_tree_layout.bl_idname,
            text="Tree Layout (Selected)",
        )
        operator.layout_mode = 'TREE'
        operator = column.operator(
            NODE_OT_tree_layout.bl_idname,
            text="Compact Selected by Distance",
        )
        operator.layout_mode = 'COMPACT'
        column.operator(
            NODE_OT_optimize_group_io.bl_idname,
            text="Optimize Group Input / Output",
        )

        layout.separator()
        layout.operator(
            NODE_OT_orthogonalize.bl_idname,
            text="Create 90-Degree Routes",
        )

        preferences = _get_preferences()
        if preferences:
            layout.separator()
            layout.prop(preferences, "auto_square")


# store keymaps here to access after registration
addon_keymaps = []
_auto_timer_running = False
_auto_state = {}


class SquareNoodlesPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    auto_square: bpy.props.BoolProperty(
        name="Automatic Squaring",
        description="Automatically square selected noodles after nodes or links change",
        default=True,
    )
    auto_delay: bpy.props.FloatProperty(
        name="Automatic Delay",
        description="Seconds to wait after a change before squaring noodles",
        default=0.5,
        min=0.1,
        max=2.0,
    )
    auto_all_nodes: bpy.props.BoolProperty(
        name="Automatically Process All Nodes",
        description="Process the whole active tree after every edit; leave disabled for best performance on large node groups",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "auto_square")
        layout.prop(self, "auto_delay")
        layout.prop(self, "auto_all_nodes")


def _get_preferences():
    addon = bpy.context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def _tree_signature(tree):
    """Return a lightweight snapshot of layout changes in collection order."""
    nodes = tuple(
        (
            node.as_pointer(),
            round(float(node.location.x), 3),
            round(float(node.location.y), 3),
            round(float(node.dimensions.x), 3),
            round(float(node.dimensions.y), 3),
            bool(node.hide),
        )
        for node in tree.nodes
    )
    links = tuple(
        (
            link.from_node.as_pointer(),
            link.from_socket.identifier,
            link.to_node.as_pointer(),
            link.to_socket.identifier,
        )
        for link in tree.links
    )
    return nodes, links


def _tree_layout_ready(tree):
    """True once every linked non-reroute node has been drawn by the editor."""
    linked_nodes = {
        node
        for link in tree.links
        for node in (link.from_node, link.to_node)
        if node.bl_idname != 'NodeReroute'
    }
    return all(node.dimensions.x > 0 and node.dimensions.y > 0 for node in linked_nodes)


def _auto_square_timer():
    """Poll visible node editors and square after a change settles."""
    global _auto_state

    if not _auto_timer_running:
        return None

    preferences = _get_preferences()
    if preferences and not preferences.auto_square:
        _auto_state.clear()
        return 0.5

    delay = preferences.auto_delay if preferences else 0.35
    now = time.monotonic()
    seen_trees = set()

    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if not screen:
            continue

        for area in screen.areas:
            if area.type != 'NODE_EDITOR':
                continue

            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue

            try:
                with bpy.context.temp_override(
                    window=window,
                    screen=screen,
                    area=area,
                    region=region,
                ):
                    if bpy.context.space_data.node_tree is None:
                        continue

                    tree, _ = get_active_tree(bpy.context)
                    tree_key = tree.as_pointer()
                    if tree_key in seen_trees:
                        continue
                    seen_trees.add(tree_key)

                    signature = _tree_signature(tree)
                    layout_ready = _tree_layout_ready(tree)
                    state = _auto_state.get(tree_key)
                    if state is None:
                        _auto_state[tree_key] = {
                            'signature': signature,
                            'changed_at': now,
                            'dirty': False,
                            'layout_ready': layout_ready,
                        }
                        continue

                    if not layout_ready:
                        state['signature'] = signature
                        state['changed_at'] = now
                        state['dirty'] = False
                        state['layout_ready'] = False
                        continue

                    if not state.get('layout_ready', False):
                        state['signature'] = signature
                        state['changed_at'] = now
                        state['dirty'] = False
                        state['layout_ready'] = True
                        continue

                    if signature != state['signature']:
                        state['signature'] = signature
                        state['changed_at'] = now
                        state['dirty'] = True
                        continue

                    if not state.get('dirty', False):
                        continue

                    if now - state['changed_at'] < delay:
                        continue

                    bpy.ops.node.orthogonalize(
                        auto_all=preferences.auto_all_nodes if preferences else False,
                        automatic=True,
                    )
                    _auto_state[tree_key] = {
                        'signature': _tree_signature(tree),
                        'changed_at': now,
                        'dirty': False,
                        'layout_ready': True,
                    }
            except (AttributeError, ReferenceError, RuntimeError):
                # Areas and node trees can disappear while Blender changes screens.
                continue

    for tree_key in tuple(_auto_state):
        if tree_key not in seen_trees:
            _auto_state.pop(tree_key, None)

    return 0.5


def register():
    global _auto_timer_running, _auto_state

    bpy.utils.register_class(SquareNoodlesPreferences)
    bpy.utils.register_class(NODE_OT_orthogonalize)
    bpy.utils.register_class(NODE_OT_tree_layout)
    bpy.utils.register_class(NODE_OT_optimize_group_io)
    bpy.utils.register_class(NODE_PT_orthogonalizer_tools)

    # handle the keymap
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    # apparently the "name" field below is an enum with 190 options and they're not documented. Yeesh.
    if kc:
        km = kc.keymaps.new(name='Node Editor', space_type='NODE_EDITOR')
        kmi = km.keymap_items.new(
            NODE_OT_orthogonalize.bl_idname,
            'COMMA',
            'PRESS',
            ctrl=False,
            shift=True,
        )
        addon_keymaps.append((km, kmi))

    _auto_state = {}
    _auto_timer_running = True
    if not bpy.app.timers.is_registered(_auto_square_timer):
        bpy.app.timers.register(
            _auto_square_timer,
            first_interval=0.5,
            persistent=True,
        )


def unregister():
    global _auto_timer_running, _auto_state

    _auto_timer_running = False
    _auto_state.clear()
    if bpy.app.timers.is_registered(_auto_square_timer):
        bpy.app.timers.unregister(_auto_square_timer)


    # handle the keymap
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    bpy.utils.unregister_class(NODE_PT_orthogonalizer_tools)
    bpy.utils.unregister_class(NODE_OT_optimize_group_io)
    bpy.utils.unregister_class(NODE_OT_tree_layout)
    bpy.utils.unregister_class(NODE_OT_orthogonalize)
    bpy.utils.unregister_class(SquareNoodlesPreferences)


if __name__ == '__main__':
    register()
