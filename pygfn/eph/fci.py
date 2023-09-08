import numpy

import pyscf
from pyscf import fci, lib

import pygfn
from pygfn.fci import _pack
from pygfn.eph._fci import make_shape

def _gen_hop_direct(gfn_obj, comp="ip", verbose=None):
    assert comp in ["ip", "ea"]

    nsite = gfn_obj.nsite
    nmode = gfn_obj.nmode
    nph_max = gfn_obj.nph_max
    nelec = gfn_obj._nelec_ip if comp == "ip" else gfn_obj._nelec_ea

    h1e = gfn_obj._h1e
    eri = gfn_obj._eri
    h1e1p = gfn_obj._h1e1p
    h1p = gfn_obj._h1p
    ene0 = gfn_obj.ene0

    vec_hdiag = gfn_obj._base.make_hdiag(h1e, eri, h1e1p, h1p, nsite, nelec, nmode, nph_max)
    vec_size = vec_hdiag.size
    vec_ones = numpy.ones(vec_size)

    shape = make_shape(nsite, nelec, nmode, nph_max)
    assert numpy.prod(shape) == vec_size

    hop = gfn_obj._base.gen_hop(h1e, eri, h1e1p, h1p, nsite, nelec, nmode, nph_max)

    def gen_hv0(omega, eta):
        def hv0(v):
            c = v.reshape(shape)
            hc_real = hop(c.real)
            hc_imag = hop(c.imag)
            hc0 = hc_real + 1j * hc_imag - ene0 * c
            return _pack(hc0.reshape(-1), omega, eta, v=v, comp=comp)
        return hv0

    def gen_hd0(omega, eta):
        return _pack(vec_hdiag - ene0, omega, eta, v=vec_ones, comp=comp)

    return gen_hv0, gen_hd0

class WithPhonon(pygfn.fci.DirectFullConfigurationInteraction):
    nmode = None # Number of phonon modes
    nph_max = 4  # Maximum number of phonons in each mode

    _h1p   = None # Phonon Hamiltonian
    _h1e1p = None # Electron-phonon interaction Hamiltonian

    def __init__(self, m=None, h1p=None, h1e1p=None):
        super().__init__(m=m)
        self._h1p = h1p
        self._h1e1p = h1e1p

    def _is_build(self):
        is_build = super()._is_build()
        is_build = is_build and self._h1p is not None
        is_build = is_build and self._h1e1p is not None
        return is_build

    def _check_sanity(self):
        assert self._base is not None

        nsite = self.nsite
        nmode = self.nmode
        nph_max = self.nph_max
        nelec = self._nelec
        assert nelec[0] >= 0 and nelec[1] >= 0

        ene0 = self.ene0
        assert ene0 is not None

        shape  = [fci.cistring.num_strings(nsite, n) for n in nelec]
        shape += [(nph_max + 1) for alph in range(nmode)]
        size = numpy.prod(shape)
        vec0 = self.vec0.reshape(size,)
        ci0 = vec0.reshape(shape)

        h1e = numpy.asarray(self._h1e)
        if h1e.ndim == 2:
            assert h1e.shape == (nsite, nsite)
        elif h1e.ndim == 3:
            assert h1e.shape == (2, nsite, nsite)

        assert self._eri is not None

        h1p = numpy.asarray(self._h1p)
        assert h1p.shape == (nmode, nmode)

        # As the electron dimensions are symmetric, h1e1p might
        # be transformed to a 2D array (nsite2, nmode).
        # nsite2 = nsite * (nsite + 1) // 2
        h1e1p = numpy.asarray(self._h1e1p)
        if h1e1p.ndim == 3:
            assert h1e1p.shape == (nsite, nsite, nmode)
        elif h1e1p.ndim == 4:
            assert h1e1p.shape == (2, nsite, nsite, nmode)

    def get_rhs_ip(self, vec0=None, orb_list=None, verbose=None):
        norb = self.norb
        orb_list = orb_list if orb_list is not None else range(norb)

        vec0 = self.vec0 if vec0 is None else vec0
        na, nb = vec0.shape[:2]
        np = vec0.reshape(na * nb, -1).shape[1]

        gen_rhs_ip = lambda v: super().get_rhs_ip(vec0=v, orb_list=orb_list, verbose=verbose)
        rhs_ip = [gen_rhs_ip(vec0.reshape(na * nb, -1)[:, i]) for i in range(np)]
        rhs_ip = numpy.asarray(rhs_ip).transpose([1, 2, 3, 0]).reshape(len(orb_list), -1)

        return rhs_ip

    def get_lhs_ip(self, vec0=None, orb_list=None, verbose=None):
        norb = self.norb
        orb_list = orb_list if orb_list is not None else range(norb)

        vec0 = self.vec0 if vec0 is None else vec0
        na, nb = vec0.shape[:2]
        np = vec0.reshape(na * nb, -1).shape[1]

        gen_lhs_ip = lambda v: super().get_lhs_ip(vec0=v, orb_list=orb_list, verbose=verbose)
        lhs_ip = [gen_lhs_ip(vec0.reshape(na * nb, -1)[:, i]) for i in range(np)]
        lhs_ip = numpy.asarray(lhs_ip).transpose([1, 2, 3, 0]).reshape(len(orb_list), -1)

        return lhs_ip

    def get_rhs_ea(self, vec0=None, orb_list=None, verbose=None):
        norb = self.norb
        orb_list = orb_list if orb_list is not None else range(norb)

        vec0 = self.vec0 if vec0 is None else vec0
        na, nb = vec0.shape[:2]
        np = vec0.reshape(na * nb, -1).shape[1]

        gen_rhs_ea = lambda v: super().get_rhs_ea(vec0=v, orb_list=orb_list, verbose=verbose)
        rhs_ea = [gen_rhs_ea(vec0.reshape(na * nb, -1)[:, i]) for i in range(np)]
        rhs_ea = numpy.asarray(rhs_ea).transpose([1, 2, 3, 0]).reshape(len(orb_list), -1)

        return rhs_ea

    def get_lhs_ea(self, vec0=None, orb_list=None, verbose=None):
        norb = self.norb
        orb_list = orb_list if orb_list is not None else range(norb)

        vec0 = self.vec0 if vec0 is None else vec0
        na, nb = vec0.shape[:2]
        np = vec0.reshape(na * nb, -1).shape[1]

        gen_lhs_ea = lambda v: super().get_lhs_ea(vec0=v, orb_list=orb_list, verbose=verbose)
        lhs_ea = [gen_lhs_ea(vec0.reshape(na * nb, -1)[:, i]) for i in range(np)]
        lhs_ea = numpy.asarray(lhs_ea).transpose([1, 2, 3, 0]).reshape(len(orb_list), -1)

        return lhs_ea

    def gen_hop_ip(self, verbose=None):
        return _gen_hop_direct(self, comp="ip", verbose=verbose)

    def gen_hop_ea(self, verbose=None):
        return _gen_hop_direct(self, comp="ea", verbose=verbose)

def FCIGF(hf_obj=hf_obj, method="slow", **kwargs):
    if method.lower() == "direct":
        return FullConfigurationInteractionDirectSpin1(hf_obj=hf_obj, **kwargs)

    else:
        raise NotImplementedError

if __name__ == '__main__':
    nsite = 2
    nmode = 2
    nph_max = 4
    nroots = 5

    u = 1.5
    g = 0.5

    h1e = numpy.zeros((nsite, nsite))
    idx_site = numpy.arange(nsite - 1)
    h1e[idx_site + 1, idx_site] = h1e[idx_site, idx_site + 1] = -1.0

    idx_site = numpy.arange(nsite)
    idx_mode = numpy.arange(nmode)
    eri = numpy.zeros((nsite, nsite, nsite, nsite))
    eri[idx_site, idx_site, idx_site, idx_site] = u

    h1e1p = numpy.zeros((nsite, nsite, nmode))
    h1e1p[idx_site, idx_site, idx_mode] = g

    idx_mode = numpy.arange(nmode - 1)
    h1p = numpy.eye(nmode) * 1.1
    h1p[idx_mode + 1, idx_mode] = h1p[idx_mode, idx_mode + 1] = 0.1

    nelecs = [(ia, ib) for ia in range(nsite + 1) for ib in range(ia + 1)]

    for nelec in nelecs:
        fci_obj = pygfn.eph.FCI()
        ene_1, c_1 = fci_obj.kernel(h1e, eri, h1e1p, h1p, nmode, nsite, nelec, nph_max=nph_max, nroots=nroots)

        gfn_obj = FCIGF(h1e=h1e, eri=eri, h1p=h1p, h1e1p=h1e1p, nelec=nelec, nph_max=nph_max)
        gfn_obj.build()
        gfn_ip, gfn_ea = gfn_obj.kernel(omega_list, eta=eta, ps=ps, qs=qs)
