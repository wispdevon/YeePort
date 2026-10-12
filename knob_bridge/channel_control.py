"""Independent RGB and warm-white levels using native HA channel fields."""
import re


def light_members(entity, states):
    visited, members = set(), []
    def visit(target):
        if not isinstance(target, str) or not re.fullmatch(r'light\.[a-z0-9_]+', target):
            raise ValueError('Invalid light group member')
        if target in visited:
            return
        visited.add(target)
        if len(visited) > 128:
            raise ValueError('Light group is too large')
        state = states.get(target)
        if not state or state.get('state') in ('unavailable', 'unknown'):
            return
        nested = state.get('attributes', {}).get('entity_id')
        if isinstance(nested, list):
            for child in nested:
                visit(child)
        else:
            members.append(state)
    visit(entity)
    return members


def native_levels(state):
    if state.get('state') != 'on':
        return 0, 0
    a = state.get('attributes', {})
    b, mode = a.get('brightness'), a.get('color_mode')
    if type(b) is not int or not 0 <= b <= 255:
        return 0, 0
    if mode == 'color_temp':
        return 0, b * 100 / 255
    channels = a.get('rgbww_color') if mode == 'rgbww' else a.get('rgbw_color') if mode == 'rgbw' else a.get('rgb_color')
    if not isinstance(channels, (list, tuple)) or len(channels) < 3:
        return 0, 0
    rgb = max(channels[:3]) * b * 100 / (255 * 255)
    warm = channels[-1] * b * 100 / (255 * 255) if mode in ('rgbw', 'rgbww') else 0
    return rgb, warm


def selected_rgb(members, fallback):
    for state in members:
        a = state.get('attributes', {})
        mode = a.get('color_mode')
        if mode not in ('rgb', 'rgbw', 'rgbww'):
            continue
        channels = a.get(mode + '_color')
        if isinstance(channels, (list, tuple)) and len(channels) >= 3 and max(channels[:3]) > 0:
            peak = max(channels[:3])
            return [round(v * 255 / peak) for v in channels[:3]]
    return list(fallback)


def independent_display_state(entity, states):
    members = light_members(entity, states)
    if not members:
        return None
    rgb_levels, warm_levels = [], []
    for state in members:
        a = state.get('attributes', {})
        modes = a.get('supported_color_modes', [])
        rgb, warm = native_levels(state)
        if any(mode in modes for mode in ('rgb', 'rgbw', 'rgbww')):
            rgb_levels.append(rgb)
        if any(mode in modes for mode in ('rgbw', 'rgbww')):
            warm_levels.append(warm)
    rgb = round(sum(rgb_levels) / len(rgb_levels)) if rgb_levels else 0
    warm = round(sum(warm_levels) / len(warm_levels)) if warm_levels else 0
    return {'rgb': (rgb > 0, rgb), 'warm': (warm > 0, warm)}


def blend_services(entity, states, rgb, rgb_level, warm_level, kelvin=2700):
    if any(type(v) is not int or not 0 <= v <= 100 for v in (rgb_level, warm_level)):
        raise ValueError('Invalid channel brightness')
    if len(rgb) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in rgb):
        raise ValueError('Invalid RGB color')
    calls = []
    for state in light_members(entity, states):
        target, a = state['entity_id'], state.get('attributes', {})
        modes = a.get('supported_color_modes', [])
        if 'rgbww' in modes or 'rgbw' in modes:
            absolute = [v * rgb_level / 100 for v in rgb]
            absolute += [0, 255 * warm_level / 100] if 'rgbww' in modes else [255 * warm_level / 100]
            peak = max(absolute)
            if peak == 0:
                calls.append(('turn_off', {'entity_id': target}))
            else:
                field = 'rgbww_color' if 'rgbww' in modes else 'rgbw_color'
                calls.append(('turn_on', {'entity_id': target, 'brightness': max(1, round(peak)),
                                         field: [round(v * 255 / peak) for v in absolute]}))
        elif 'rgb' in modes and rgb_level > 0:
            calls.append(('turn_on', {'entity_id': target, 'rgb_color': list(rgb),
                                     'brightness_pct': rgb_level}))
        elif 'color_temp' in modes and warm_level > 0:
            temperature = min(a.get('max_color_temp_kelvin', 6500),
                              max(a.get('min_color_temp_kelvin', 2000), kelvin))
            calls.append(('turn_on', {'entity_id': target, 'color_temp_kelvin': temperature,
                                     'brightness_pct': warm_level}))
        else:
            calls.append(('turn_off', {'entity_id': target}))
    if not calls:
        raise ValueError('No available lights in the configured target')
    return calls
