"""Bounded user-imported light entries and local English display labels."""
import io
import re

from PIL import Image, ImageDraw, ImageFont

CONTROL_TYPES = {'switch': 1, 'brightness': 2, 'color': 4}


def base_slot_count(options):
    if options.get('separate_brightness_controls', False):
        return 6 if options.get('ha_lights_menu_enabled', False) else 5
    return 3


def english_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[ -~]{1,24}', value) or not value.strip():
        raise ValueError('Use an English menu name of 1–24 characters.')
    return value.strip()


def imported_menu(options):
    records = options.get('imported_lights', [])
    start = base_slot_count(options)
    if not isinstance(records, list) or len(records) > 8 - start:
        raise ValueError(f'This menu has room for {8 - start} imported lights.')
    rows, seen = [], set()
    for index, record in enumerate(records, start + 1):
        if not isinstance(record, dict):
            raise ValueError('Invalid imported light.')
        entity = record.get('entity_id')
        if not isinstance(entity, str) or not re.fullmatch(r'light\.[a-z0-9_]+', entity):
            raise ValueError('Choose a Home Assistant light or light group.')
        if entity in seen:
            raise ValueError('Each light can only be imported once.')
        controls = record.get('controls', 'brightness')
        if controls not in CONTROL_TYPES:
            raise ValueError('Invalid light controls.')
        seen.add(entity)
        rows.append({'slot': index, 'entity_id': entity, 'name': english_name(record.get('name')),
                     'controls': controls})
    return rows


def light_controls(state):
    modes = state.get('attributes', {}).get('supported_color_modes', [])
    color = 'color_temp' in modes and any(m in modes for m in ('rgb', 'rgbw', 'rgbww', 'hs', 'xy'))
    return 'color' if color else ('switch' if modes == ['onoff'] else 'brightness')


def prepare_import(options, selected, states):
    records = []
    if not isinstance(selected, list):
        raise ValueError('Choose a list of lights.')
    for record in selected:
        if not isinstance(record, dict):
            raise ValueError('Invalid imported light.')
        entity = record.get('entity_id')
        state = states.get(entity) if isinstance(entity, str) else None
        if state is None or not entity.startswith('light.'):
            raise ValueError('The selected light was not found in Home Assistant.')
        records.append({'entity_id': entity, 'name': record.get('name'), 'controls': light_controls(state)})
    # Apply the same strict validation used when the bridge loads its options.
    return [{k: v for k, v in row.items() if k != 'slot'}
            for row in imported_menu(dict(options, imported_lights=records))]


def render_label(name):
    """Match the verified vendor label canvas: 240×48, eight-bit RGBA PNG."""
    name = english_name(name)
    image = Image.new('RGBA', (240, 48), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for size in range(36, 7, -1):
        font = ImageFont.truetype('DejaVuSans.ttf', size)
        if draw.textlength(name, font=font) <= 232:
            break
    draw.text((120, 24), name, font=font, fill=(255, 255, 255, 255), anchor='mm')
    output = io.BytesIO()
    image.save(output, format='PNG', optimize=True)
    return output.getvalue()
