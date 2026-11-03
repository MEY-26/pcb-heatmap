"""Explicit substrate categories; no guessed vendor conductivity presets.

The numerical model accepts one homogeneous electrically insulating substrate,
with separate in-plane and through-plane constant thermal conductivities.
Material names document the user's choice; choosing a category never changes k.
Legacy ``fr4_k`` scenarios retain their exact isotropic numerical meaning.
"""
from __future__ import annotations

import math
from numbers import Real

try:
    from .model import AnalysisError
except ImportError:
    from model import AnalysisError


SUBSTRATE_MATERIALS = ('custom', 'fr4', 'ceramic', 'metal_core')

# Primary manufacturer references explaining why there is no universal FR4,
# ceramic, or aluminium-board k value. These are documentation, not downloads
# or runtime lookups, and are not automatic numerical presets.
MATERIAL_REFERENCES = {
    'ceramic': 'https://www.ceramtec-industrial.com/en/products-applications/substrates/aln-substrates',
    'metal_core': 'https://tclad.com/products/insulated-metal-substrate/',
}


def substrate_conductivities(settings, *, require_thermal=True):
    """Return validated (k_xy, k_z), preserving old isotropic scenarios.

    Metal-core boards require independently resolved dielectric and metal-base
    layers. Substituting bulk aluminium k for every non-copper volume would
    invent a thermal path through the electrical insulation, so reject this
    unsupported construction explicitly instead of returning a heatmap.
    """
    material = settings.substrate_material
    if material not in SUBSTRATE_MATERIALS:
        raise AnalysisError('Unknown substrate material.', code='unknown_substrate_material',
                            details={'substrate_material': material})
    if material == 'metal_core' and require_thermal:
        raise AnalysisError(
            'Metal-core PCB thermal analysis requires separate insulating dielectric and metal-base layers. '
            'This model does not yet resolve a metal base; do not use bulk aluminium conductivity '
            'for the insulating substrate.', code='unsupported_metal_core')
    values = (settings.fr4_k,
              settings.fr4_k if settings.substrate_k_z is None else settings.substrate_k_z)
    result = []
    for direction, value in zip(('in-plane', 'through-plane'), values):
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
            raise AnalysisError(f'Substrate {direction} conductivity must be finite and positive.',
                                code='invalid_substrate_conductivity', details={'direction': direction})
        result.append(float(value))
    return tuple(result)
