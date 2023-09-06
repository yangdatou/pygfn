import numpy

import pyscf
from pyscf import fci, lib, ao2mo

from pyscf.fci import direct_ep
from pyscf.fci.cistring import num_strings
from pyscf.fci.cistring import gen_linkstr_index
from pyscf.fci.direct_spin1 import _unpack_nelec
from pyscf.fci.direct_ep import slices_for, slices_for_cre, slices_for_des

def make_shape(nsite, nelec, nmode, nph_max):
    nelec_alph, nelec_beta = _unpack_nelec(nelec)
    na = num_strings(nsite, nelec_alph)
    nb = num_strings(nsite, nelec_beta)
    return (na, nb) + (nph_max + 1,) * nmode

def contract_h1e(h1e, v, nsite, nelec, nmode, nph_max, fci_obj=None):
    if fci_obj is None:
        fci_obj = pyscf.fci.direct_spin1

    h1e = numpy.asarray(h1e)
    shape = make_shape(nsite, nelec, nmode, nph_max)
    c = v.reshape(shape)
    na, nb = shape[:2]
    c = c.reshape(na * nb, -1)
    np = c.shape[1]

    gen_hc = lambda i: fci_obj.contract_1e(h1e, c[:, i], nsite, nelec).reshape(na, nb)
    hc = [gen_hc(i) for i in range(np)]
    hc = numpy.asarray(hc).transpose(1, 2, 0)

    return hc.reshape(shape)

def contract_h2e(h2e, v, nsite, nelec, nmode, nph_max, fci_obj=None):
    if fci_obj is None:
        fci_obj = pyscf.fci.direct_spin1

    h2e = numpy.asarray(h2e)
    shape = make_shape(nsite, nelec, nmode, nph_max)
    c = v.reshape(shape)
    na, nb = shape[:2]
    c = c.reshape(na * nb, -1)
    np = c.shape[1]

    gen_hc = lambda i: fci_obj.contract_2e(h2e, c[:, i], nsite, nelec).reshape(na, nb)
    hc = [gen_hc(i) for i in range(np)]
    hc = numpy.asarray(hc).transpose(1, 2, 0)

    return hc.reshape(shape)

def contract_h1e1p(h1e1p, v, nsite, nelec, nmode, nph_max, fci_obj=None):
    if fci_obj is None:
        fci_obj = pyscf.fci.direct_spin1

    h1e1p = numpy.asarray(h1e1p)
    shape = make_shape(nsite, nelec, nmode, nph_max)
    c = v.reshape(shape)
    hc = numpy.zeros_like(c)
    na, nb = shape[:2]

    c = c.reshape(na * nb, -1)
    np = c.shape[1]

    factors = numpy.sqrt(numpy.arange(1, nph_max + 1))
    for alph in range(nmode):
        gen_hc_e = lambda i: fci_obj.contract_1e(h1e1p[..., alph], c[:, i], nsite, nelec).reshape(na, nb)
        hc_e = [gen_hc_e(i) for i in range(np)]
        hc_e = numpy.asarray(hc_e).transpose(1, 2, 0)
        hc_e = hc_e.reshape(shape)

        for nph, f in enumerate(factors):
            s0 = slices_for(alph, nmode, nph)
            s1 = slices_for_cre(alph, nmode, nph)

            hc[s1] += hc_e[s0] * f
            hc[s0] += hc_e[s1] * f

    return hc.reshape(shape)

def contract_h1p(h1p, v, nsite, nelec, nmode, nph_max, fci_obj=None):
    # Phonon-phonon coupling
    cishape = make_shape(nsite, nelec, nmode, nph_max)
    c = v.reshape(cishape)
    hc = numpy.zeros_like(c)

    factors = numpy.sqrt(numpy.arange(1, nph_max + 1))
    t1 = numpy.zeros((nmode,) + cishape)

    for alph in range(nmode):
        for nph, f in enumerate(factors):
            s0 = slices_for(alph, nmode, nph)
            s1 = slices_for_cre(alph, nmode, nph)
            t1[(alph,) + s0] += c[s1] * f

    t1 = lib.dot(h1p, t1.reshape(nmode, -1)).reshape(t1.shape)

    for alph in range(nmode):
        for nph, f in enumerate(factors):
            s0 = slices_for(alph, nmode, nph)
            s1 = slices_for_cre(alph, nmode, nph)
            hc[s1] += t1[(alph,) + s0] * f

    return hc.reshape(cishape)

def make_hdiag(h1e, eri, h1e1p, h1p, nsite, nelec, nmode, nph_max, fci_obj=None):
    if fci_obj is None:
        fci_obj = pyscf.fci.direct_spin1

    shape = make_shape(nsite, nelec, nmode, nph_max)
    na, nb = shape[:2]

    hdiag_e = fci_obj.make_hdiag(h1e, eri, nsite, nelec).reshape(na, nb)
    hdiag   = numpy.hstack([hdiag_e] * (nph_max + 1) ** nmode).reshape(shape)

    for alph in range(nmode):
        for nph in range(nph_max+1):
            s0 = [slice(None, None, None)] * (2 + nmode)  # +2 for electron indices
            s0[2 + alph] = nph
            s0 = tuple(s0)

            hdiag[s0] += nph + 1

    return hdiag.ravel()

def kernel(h1e, eri, h1e1p, h1p, nsite, nmode, nelec, nph_max,
           tol=1e-9, max_cycle=100, verbose=0, ci0=None, h0=0.0,
           noise=1e-6, fci_obj=None, **kwargs):
    if fci_obj is None:
        fci_obj = pyscf.fci.direct_spin1

    shape = make_shape(nsite, nelec, nmode, nph_max)

    if ci0 is None:
        # Add noise for initial guess, remove it if problematic
        ci0 = numpy.zeros(shape)
        ci0.__setitem__((0, 0) + (0,) * nmode, 1.0)

        if noise is not None:
            ci0[0, :] += numpy.random.random(ci0[0, :].shape) * noise
            ci0[:, 0] += numpy.random.random(ci0[:, 0].shape) * noise

    else:
        ci0 = ci0.reshape(shape)

    h1e = numpy.asarray(h1e)
    eri = numpy.asarray(eri)
    h1e1p = numpy.asarray(h1e1p)
    h1p = numpy.asarray(h1p)
    h2e = fci_obj.absorb_h1e(h1e, eri, nsite, nelec, .5)
    def hop(v):
        c = v.reshape(shape)
        hc  = contract_h2e(h2e, c, nsite, nelec, nmode, nph_max, fci_obj=fci_obj)
        hc += contract_h1e1p(h1e1p, c, nsite, nelec, nmode, nph_max, fci_obj=fci_obj)
        hc += contract_h1p(h1p, c, nsite, nelec, nmode, nph_max, fci_obj=fci_obj)
        return hc.ravel()

    hdiag = make_hdiag(h1e, eri, h1e1p, h1p, nsite, nelec, nmode, nph_max, fci_obj=fci_obj)
    precond = lambda x, e, *args: x / (hdiag - e + 1e-4)
    e, c = lib.davidson(
        hop, ci0.reshape(-1), precond,
        tol=tol, max_cycle=max_cycle,
        verbose=verbose, **kwargs
    )
    return e + h0, c

if __name__ == '__main__':
    nsite = 4
    nmode = 4
    nph_max = 2

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
        ene_0, c_0 = fci.direct_ep.kernel(h1e, u, g, h1p, nsite, nelec, nph_max,
                                          tol=1e-10, max_cycle=1000, verbose=0, nroots=10)

        import pygfn.eph
        fci_obj = pygfn.eph.FCI()
        ene_1, c_1 = fci_obj.kernel(h1e, eri, h1e1p, h1p, nmode, nsite, nelec, nph_max=nph_max, nroots=10)

        err = numpy.linalg.norm(ene_1 - ene_0)
        print(err)
        assert err < 1e-8

