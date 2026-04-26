"""Mock bpy + mathutils so pipeline modules can be imported without Blender."""
import math
import sys
from unittest.mock import MagicMock


class _Vec:
    def __init__(self, coords):
        self._c = tuple(float(x) for x in coords)

    @property
    def x(self): return self._c[0]
    @property
    def y(self): return self._c[1]
    @property
    def z(self): return self._c[2]

    def __iter__(self): return iter(self._c)
    def __repr__(self): return f"Vector{self._c}"

    def __sub__(self, o): return _Vec(a - b for a, b in zip(self._c, o._c))
    def __add__(self, o): return _Vec(a + b for a, b in zip(self._c, o._c))
    def __mul__(self, s): return _Vec(x * s for x in self._c)
    def __rmul__(self, s): return self.__mul__(s)
    def __truediv__(self, s): return _Vec(x / s for x in self._c)
    def __neg__(self): return _Vec(-x for x in self._c)
    def __getitem__(self, i): return self._c[i]
    def __len__(self): return len(self._c)

    @property
    def length(self): return math.sqrt(sum(x * x for x in self._c))

    def normalized(self):
        n = self.length or 1.0
        return _Vec(x / n for x in self._c)

    def dot(self, o): return sum(a * b for a, b in zip(self._c, o._c))

    def cross(self, o):
        a, b = self._c, o._c
        return _Vec([
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ])

    def copy(self): return _Vec(self._c)
    def to_tuple(self, precision=None): return self._c


class _Quaternion:
    def __init__(self, *args):
        if len(args) == 4:
            self.w, self.x, self.y, self.z = args
        elif len(args) == 1:
            seq = list(args[0])
            self.w, self.x, self.y, self.z = seq
        else:
            self.w, self.x, self.y, self.z = 1.0, 0.0, 0.0, 0.0

    def __iter__(self): return iter([self.w, self.x, self.y, self.z])
    def normalized(self): return self
    def copy(self): return _Quaternion(self.w, self.x, self.y, self.z)


_mathutils_mod = MagicMock()
_mathutils_mod.Vector = _Vec
_mathutils_mod.Quaternion = _Quaternion

_bpy_mod = MagicMock()
# ray_cast must return an iterable: (hit, loc, normal, ...)
_bpy_mod.context.scene.ray_cast.return_value = (False, _Vec([0,0,0]), _Vec([0,0,1]))
_bpy_mod.context.evaluated_depsgraph_get.return_value = MagicMock()

sys.modules.setdefault("bpy", _bpy_mod)
sys.modules.setdefault("mathutils", _mathutils_mod)
