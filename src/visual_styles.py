"""Explicit, job-persisted visual style presets, independent of video provider."""
from copy import deepcopy

PRESETS = {
    'photorealistic': (True, 'Photorealistic photography, natural proportions, lifelike skin texture and materials; no cartoon, illustration, or stylized 3D rendering.'),
    'cinematic_realism': (True, 'Live-action cinematic realism, natural human proportions and skin texture, film-still composition and motivated lighting; no cartoon or illustration.'),
    'animation_3d': (False, 'Stylized 3D animated-film rendering, expressive characters, rounded forms, detailed materials and dimensional lighting.'),
    'cartoon_2d': (False, 'Hand-drawn 2D cartoon, clean outlines, simplified shapes, flat colors and expressive poses.'),
    'anime': (False, 'Anime illustration, clean linework, cel shading, expressive drawn characters and detailed painted backgrounds.'),
    'watercolor': (False, 'Watercolor illustration, translucent pigment washes, textured paper, soft edges and delicate brushwork.'),
    'comic': (False, 'Comic-book illustration, bold ink contours, graphic shadows and vivid colors; single image without panels, lettering or speech bubbles.'),
    'storybook': (False, 'Detailed painted storybook illustration, charming stylized characters, soft textures and atmospheric lighting.'),
}
CHOICES = ('default', *PRESETS)


def select_style(spec: dict, preset: str | None) -> dict:
    result = deepcopy(spec)
    if preset in (None, 'default'):
        return result
    realistic, description = PRESETS[preset]
    style = result.setdefault('visual', {}).setdefault('style', {})
    style.update(preset=preset, realistic=realistic, cinematic=True, style_description=description)
    return result


def persist_style(style: dict, spec: dict) -> dict:
    result = deepcopy(style)
    chosen = spec.get('visual', {}).get('style', {})
    if chosen.get('preset') in PRESETS:
        result.update(preset=chosen['preset'], visual=chosen['style_description'],
                      realistic=chosen['realistic'], cinematic=chosen['cinematic'])
    return result


def effective_visual_spec(spec: dict, job: dict) -> dict:
    """Prevent the shared YAML's cartoon defaults contradicting a saved job."""
    preset = job.get('style', {}).get('preset')
    result = select_style(spec, preset if preset in PRESETS else None)
    return result.get('visual', {})


def style_instruction(job: dict) -> str:
    style = job.get('style', {})
    if style.get('preset') not in PRESETS:
        return ''
    return ('\nVISUAL STYLE OVERRIDE: The saved job style is authoritative for rendering medium, '
            'realism and proportions, even if older scene wording or story ideas suggest another medium. '
            'Keep the story content and character identity. Apply consistently to every reference and scene. '
            + style['visual'] + '\n')
