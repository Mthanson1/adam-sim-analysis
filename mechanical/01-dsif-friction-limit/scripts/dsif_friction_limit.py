#!/usr/bin/env python3
"""
dsif_friction_limit.py
======================

Estimate the largest tool/sheet friction coefficient a DSIF (double-sided
incremental forming) setup can tolerate before frictional drag tears the sheet.

Model
-----
* Square sheet D x D x t, all four edges clamped (u = v = 0).
* Two tool contacts, one on each face at the centre. Each carries the same
  in-plane (friction) force F in +x.
* The two loads mirror each other about the mid-plane, so the sheet does not
  bend. That leaves a 2D plane-stress membrane problem with total load 2F,
  spread over the contact patch.
* Contact patch (--shape):
    square  d x d
    circle  diameter d   (hemispherical tool)
* Friction traction distribution (--dist):
    uniform   constant over the patch
    hertz     tau ~ sqrt(1 - r^2/a^2). Under full sliding, the friction traction
              follows the Hertz contact pressure of a sphere: tau = mu * p.
* Material (--model):
    elastic   linear elastic, ramp until peak stress = UTS (engineering)
    plastic   J2 (von Mises) plane-stress elastoplasticity with isotropic
              hardening, solved incrementally with Newton-Raphson
    both      run both and compare (default)

Plasticity details
------------------
Hardening (--hardening):
  swift    sigma_y = K (eps0 + ep)^n, fitted to --sy (initial yield),
           --uts (engineering UTS) and --n (hardening exponent). Considere:
           uniaxial necking at true strain n, where the true stress is
           K n^n = UTS_eng * e^n.
  perfect  sigma_y = UTS (constant). The load ramps until the sheet can no
           longer carry more load (plastic collapse). This is a check against
           the rigid-plastic limit-load estimate.

Tear criteria reported (plastic model):
  1. local necking onset: the peak equivalent plastic strain reaches the
     Considere strain (n - eps0). The local true von Mises stress then equals
     the true UTS. This is the "material reaches its UTS" condition.
  2. fracture strain (--eps_f, optional): the peak equivalent plastic strain
     reaches a ductile-fracture strain you supply.
  3. plastic collapse (perfect plasticity only).

Linking it to friction
----------------------
Friction drag = mu * F_n (F_n = normal forming force per tool). More friction
means more drag, so mu_max = F_t,crit / F_n is an UPPER bound on mu.

Caveats
-------
* Small-strain membrane theory: no thinning, no through-thickness shear under
  the patch, no stresses from the normal force. Membrane theory is weak when
  t is close to d.
* Use the thinned wall thickness t0*cos(wall angle) for a formed wall.
* Local necking by a uniaxial Considere criterion is approximate for
  multiaxial states. Real ISF formability is governed by fracture-forming
  limits and is typically much higher than in stamping.
* A real ISF contact sits on an inclined wall and covers only part of the
  circle. The flat-sheet patch here is an idealisation.

Squeeze factor
--------------
SF = tool-tip gap / sheet thickness (< 1 = squeezing). Each tool indents the
sheet by delta = t(1-SF)/2. The contact diameter comes from the tip radius R:
d = 2 sqrt(2 R delta - delta^2) (geometric chord, --contact_model plastic), or
2 sqrt(R delta) (Hertz, elastic). The sheet under the patch is thinned to SF*t.
This contact size is a lower bound: on a formed wall the tool also bears
against the inclined wall.

Output
------
The tear force per tool, F_t,crit, for each SF, and mu_max = F_t,crit / F_n as
a curve over a range of normal force F_n (table, CSV and plot), so you can read
off mu_max once F_n is known. Files are written to this study's folder:
  results/dsif_mu_vs_Fn.csv                      mu_max(F_n) table (regenerable)
  results/figures/dsif_mu_vs_Fn.png        tear force + mu_max curves
  results/figures/dsif_friction_limit.png  stress / plastic strain fields

Materials
---------
Presets come from shared/materials/sheet_metals.csv. Add a row there to make a
new --material option available.

Usage
-----
    python dsif_friction_limit.py                            # AA3003-O, R=5, SF 0.8..0.95
    python dsif_friction_limit.py --R 6 --sf 0.85,0.9 --t 0.8
    python dsif_friction_limit.py --Fn_min 200 --Fn_max 3000
    python dsif_friction_limit.py --material aa3003-h14 --eps_f 0.6
    python dsif_friction_limit.py --d 3                      # fixed contact size, no squeeze
All lengths in mm, stresses in MPa, forces in N.

Requires: numpy, scipy, matplotlib, adam_common (pip install -e shared)
"""

import argparse
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

try:
    from adam_common import apply_style, load_table, save_figure, study_paths
except ImportError:  # running without `pip install -e shared`
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
    from adam_common import apply_style, load_table, save_figure, study_paths


# ============================================================================
# Mesh
# ============================================================================
def graded_axis(D, d, n_patch, growth=1.15, fine_halfwidth_factor=1.5):
    """Node coordinates on [-D/2, D/2]. Uniform fine spacing d/n_patch out to
    +-fine_halfwidth_factor*d, then geometric growth. +-d/2 fall on nodes."""
    if n_patch % 2:
        n_patch += 1
    h = d / n_patch
    n_fine = int(round(fine_halfwidth_factor * d / h))
    pos = list(np.arange(0, n_fine + 1) * h)
    x, step = pos[-1], h
    while x < D / 2:
        step *= growth
        x += step
        pos.append(x)
    pos = np.array(pos)
    c = n_fine * h
    graded = pos[n_fine:]
    graded = c + (graded - c) * (D / 2 - c) / (graded[-1] - c)
    pos = np.concatenate([pos[:n_fine], graded])
    return np.concatenate([-pos[:0:-1], pos])


GP = np.array([-1, 1]) / np.sqrt(3.0)
GAUSS = [(xi, eta) for eta in GP for xi in GP]
XI_N = np.array([-1, 1, 1, -1])
ETA_N = np.array([-1, -1, 1, 1])


def shape_funcs(xi, eta):
    return 0.25 * (1 + XI_N * xi) * (1 + ETA_N * eta)


def B_matrices(dx, dy, xi, eta):
    dN_dxi = 0.25 * XI_N * (1 + ETA_N * eta)
    dN_deta = 0.25 * ETA_N * (1 + XI_N * xi)
    dNdx = (2.0 / dx)[:, None] * dN_dxi[None, :]
    dNdy = (2.0 / dy)[:, None] * dN_deta[None, :]
    B = np.zeros((dx.size, 3, 8))
    B[:, 0, 0::2] = dNdx
    B[:, 1, 1::2] = dNdy
    B[:, 2, 0::2] = dNdy
    B[:, 2, 1::2] = dNdx
    return B


class Mesh:
    def __init__(self, D, d, t, n_patch, growth):
        self.D, self.d, self.t = D, d, t
        xs = graded_axis(D, d, n_patch, growth)
        ys = xs.copy()
        self.xs, self.ys = xs, ys
        nx, ny = xs.size, ys.size
        self.nnode = nx * ny
        self.ndof = 2 * self.nnode
        nid = np.arange(self.nnode).reshape(ny, nx)
        conn = np.stack([nid[:-1, :-1].ravel(), nid[:-1, 1:].ravel(),
                         nid[1:, 1:].ravel(), nid[1:, :-1].ravel()], axis=1)
        self.conn = conn
        DX, DY = np.meshgrid(np.diff(xs), np.diff(ys))
        self.dx, self.dy = DX.ravel(), DY.ravel()
        X0, Y0 = np.meshgrid(xs[:-1], ys[:-1])
        self.x0, self.y0 = X0.ravel(), Y0.ravel()
        self.nel = conn.shape[0]
        self.shape2d = (ny - 1, nx - 1)
        self.detJ = self.dx * self.dy / 4.0
        self.xc, self.yc = self.x0 + self.dx / 2, self.y0 + self.dy / 2
        self.te = np.full(self.nel, t)                              # element thickness
        # (4, nel, 3, 8)
        self.Bs = np.stack([B_matrices(self.dx, self.dy, xi, eta) for xi, eta in GAUSS])

        dofs = np.empty((self.nel, 8), dtype=np.int64)
        dofs[:, 0::2] = 2 * conn
        dofs[:, 1::2] = 2 * conn + 1
        self.dofs = dofs

        X, Y = np.meshgrid(xs, ys)
        edge = (np.isclose(np.abs(X), D / 2) | np.isclose(np.abs(Y), D / 2)).ravel()
        fixed = np.concatenate([2 * np.where(edge)[0], 2 * np.where(edge)[0] + 1])
        self.edge_nodes = np.where(edge)[0]
        self.free = np.setdiff1d(np.arange(self.ndof), fixed)
        red = -np.ones(self.ndof, dtype=np.int64)
        red[self.free] = np.arange(self.free.size)
        rows = np.repeat(dofs, 8, axis=1).ravel()
        cols = np.tile(dofs, (1, 8)).ravel()
        rr, cc = red[rows], red[cols]
        self.kmask = (rr >= 0) & (cc >= 0)
        self.rr, self.cc = rr[self.kmask], cc[self.kmask]
        self.centre_node = nid[ny // 2, nx // 2]

    # --------------------------------------------------------------- assembly
    def stiffness(self, Dgp):
        """Dgp: (3,3) constant, or (4, nel, 3, 3) per Gauss point."""
        Ke = np.zeros((self.nel, 8, 8))
        w = (self.te * self.detJ)[:, None, None]
        for g in range(4):
            B = self.Bs[g]
            if Dgp.ndim == 2:
                Ke += np.einsum('eki,kl,elj->eij', B, Dgp, B) * w
            else:
                Ke += np.einsum('eki,ekl,elj->eij', B, Dgp[g], B) * w
        vals = Ke.ravel()[self.kmask]
        n = self.free.size
        return sp.csc_matrix((vals, (self.rr, self.cc)), shape=(n, n))

    def strains(self, u):
        ue = u[self.dofs]
        return np.einsum('gekj,ej->gek', self.Bs, ue)              # (4,nel,3)

    def internal_force(self, sig):
        fe = np.einsum('gekj,gek->ej', self.Bs, sig) * (self.te * self.detJ)[:, None]
        return np.bincount(self.dofs.ravel(), weights=fe.ravel(), minlength=self.ndof)

    def thin_patch(self, shape, t_patch):
        """Set the thickness of elements under the contact patch."""
        a = self.d / 2
        if shape == 'circle':
            inside = self.xc ** 2 + self.yc ** 2 < a ** 2
        else:
            inside = (np.abs(self.xc) < a) & (np.abs(self.yc) < a)
        self.te[inside] = t_patch

    # ------------------------------------------------------------------ load
    def load_vector(self, shape, dist, F_total, nsub=8):
        """Consistent nodal forces (x-direction) for total force F_total spread
        over the patch with the requested shape and distribution."""
        a = self.d / 2
        cand = np.where((self.x0 < a) & (self.x0 + self.dx > -a) &
                        (self.y0 < a) & (self.y0 + self.dy > -a))[0]
        s = (np.arange(nsub) + 0.5) / nsub * 2 - 1                 # natural coords
        XI, ETA = np.meshgrid(s, s)
        XI, ETA = XI.ravel(), ETA.ravel()
        N = np.stack([shape_funcs(xi, eta) for xi, eta in zip(XI, ETA, strict=True)])  # (ns,4)
        px = self.x0[cand, None] + (XI[None, :] + 1) / 2 * self.dx[cand, None]
        py = self.y0[cand, None] + (ETA[None, :] + 1) / 2 * self.dy[cand, None]
        if shape == 'circle':
            r2 = (px ** 2 + py ** 2) / a ** 2
            q = np.where(r2 < 1, np.sqrt(np.clip(1 - r2, 0, None)) if dist == 'hertz' else 1.0, 0.0)
        else:
            inside = (np.abs(px) < a) & (np.abs(py) < a)
            if dist == 'hertz':   # separable elliptical profile
                qx = np.clip(1 - (px / a) ** 2, 0, None)
                qy = np.clip(1 - (py / a) ** 2, 0, None)
                q = np.sqrt(qx * qy)
            else:
                q = np.ones_like(px)
            q = np.where(inside, q, 0.0)
        dA = (self.dx[cand] * self.dy[cand] / nsub ** 2)[:, None]
        fnode = np.einsum('es,sn->en', q * dA, N)                  # (ncand,4)
        f = np.zeros(self.ndof)
        np.add.at(f, 2 * self.conn[cand].ravel(), fnode.ravel())
        return f * (F_total / f.sum())                             # exact total


# ============================================================================
# Material
# ============================================================================
# Presets from shared/materials/sheet_metals.csv (E, nu, uts, sy, n).
MAT_KEYS = ('E', 'nu', 'uts', 'sy', 'n')
MATERIALS = {name: {k: props[k] for k in MAT_KEYS}
             for name, props in load_table('sheet_metals').items()}

def dmat(E, nu):
    return E / (1 - nu ** 2) * np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]])


P_MAT = np.array([[2., -1., 0.], [-1., 2., 0.], [0., 0., 6.]]) / 3.0


class J2PlaneStress:
    """Plane-stress J2 plasticity, isotropic hardening, return mapping and
    consistent tangent after de Souza Neto, Peric & Owen (2008), Ch. 9."""

    def __init__(self, E, nu, hardening, sy0, uts, n):
        self.E, self.nu = E, nu
        self.G = E / (2 * (1 + nu))
        self.C = dmat(E, nu)
        self.Cinv = np.linalg.inv(self.C)
        self.hardening = hardening
        if hardening == 'perfect':
            self.sy0 = uts
            self.ep_neck = np.inf
            self.true_uts = uts
        else:
            self.n = n
            self.K = uts * np.exp(n) / n ** n
            self.e0 = (sy0 / self.K) ** (1 / n)
            if self.e0 >= n:
                raise ValueError('yield stress too high for this n/UTS; Swift fit invalid')
            self.ep_neck = n - self.e0                              # Considere
            self.true_uts = self.K * n ** n

    def sy(self, ep):
        if self.hardening == 'perfect':
            return np.full_like(ep, self.sy0)
        return self.K * (self.e0 + ep) ** self.n

    def H(self, ep):
        if self.hardening == 'perfect':
            return np.zeros_like(ep)
        return self.n * self.K * (self.e0 + ep) ** (self.n - 1)

    def update(self, eps, epsp_n, ebar_n):
        """eps, epsp_n: (N,3); ebar_n: (N,). Returns sig, epsp, ebar, Dt (N,3,3)."""
        E, nu, G = self.E, self.nu, self.G
        sig_tr = (eps - epsp_n) @ self.C.T
        xi_tr = np.einsum('ni,ij,nj->n', sig_tr, P_MAT, sig_tr)
        syn = self.sy(ebar_n)
        phi = 0.5 * xi_tr - syn ** 2 / 3
        pl = phi > 1e-10 * syn ** 2

        sig = sig_tr.copy()
        epsp = epsp_n.copy()
        ebar = ebar_n.copy()
        Dt = np.broadcast_to(self.C, (eps.shape[0], 3, 3)).copy()
        if not pl.any():
            return sig, epsp, ebar, Dt

        st = sig_tr[pl]
        a1 = (st[:, 0] + st[:, 1]) ** 2
        a2 = (st[:, 1] - st[:, 0]) ** 2
        a3 = st[:, 2] ** 2
        ebn = ebar_n[pl]
        dg = np.zeros(st.shape[0])
        k = E / (3 * (1 - nu))
        for _ in range(60):
            uu = 1 + k * dg
            vv = 1 + 2 * G * dg
            xi = a1 / (6 * uu ** 2) + (0.5 * a2 + 2 * a3) / vv ** 2
            dxi = -k * a1 / (3 * uu ** 3) - 2 * G * (a2 + 4 * a3) / vv ** 3
            sq = np.sqrt(2 * xi / 3)
            eb = ebn + dg * sq
            syv = self.sy(eb)
            Hv = self.H(eb)
            Fv = 0.5 * xi - syv ** 2 / 3
            dF = 0.5 * dxi - (2 / 3) * syv * Hv * (sq + dg * dxi / (3 * sq))
            dg = np.maximum(dg - Fv / dF, 0.0)
            if np.max(np.abs(Fv) / syv ** 2) < 1e-12:
                break

        Xi = np.linalg.inv(self.Cinv[None] + dg[:, None, None] * P_MAT[None])
        s = np.einsum('nij,jk,nk->ni', Xi, self.Cinv, st)
        xi = np.einsum('ni,ij,nj->n', s, P_MAT, s)
        eb = ebn + dg * np.sqrt(2 * xi / 3)
        Hv = self.H(eb)
        nvec = np.einsum('nij,jk,nk->ni', Xi, P_MAT, s)
        denom = np.einsum('ni,ij,nj->n', s, P_MAT, nvec) + 2 * xi * Hv / (3 - 2 * Hv * dg)
        sig[pl] = s
        epsp[pl] = epsp_n[pl] + dg[:, None] * (s @ P_MAT.T)
        ebar[pl] = eb
        Dt[pl] = Xi - np.einsum('ni,nj->nij', nvec, nvec) / denom[:, None, None]
        return sig, epsp, ebar, Dt


def von_mises(sig):
    sxx, syy, txy = sig[..., 0], sig[..., 1], sig[..., 2]
    return np.sqrt(sxx ** 2 - sxx * syy + syy ** 2 + 3 * txy ** 2)


def max_principal(sig):
    sxx, syy, txy = sig[..., 0], sig[..., 1], sig[..., 2]
    return 0.5 * (sxx + syy) + np.sqrt((0.5 * (sxx - syy)) ** 2 + txy ** 2)


# ============================================================================
# Solvers
# ============================================================================
def elastic_unit(mesh, E, nu, f_unit):
    """Solution for F = 1 N per tool. Returns per-element peak stresses."""
    C = dmat(E, nu)
    K = mesh.stiffness(C)
    u = np.zeros(mesh.ndof)
    u[mesh.free] = spla.spsolve(K, f_unit[mesh.free])
    sig = mesh.strains(u) @ C.T
    s1 = max_principal(sig).max(axis=0).reshape(mesh.shape2d)
    vm = von_mises(sig).max(axis=0).reshape(mesh.shape2d)
    return dict(u=u, s1=s1, vm=vm)


def plastic_ramp(mesh, mat, f_unit, F_start, F_stop, dFmax, stop_ep=None,
                 tol=1e-7, maxit=25, verbose=True):
    """Load-controlled Newton ramp. F is the tangential force PER TOOL
    (f_unit holds 2 N total = 1 N per tool). Stops at F_stop, when peak ebar
    exceeds stop_ep, or at plastic collapse (increments can't converge)."""
    ngp = 4 * mesh.nel
    epsp = np.zeros((ngp, 3))
    ebar = np.zeros(ngp)
    u = np.zeros(mesh.ndof)
    u_prev = u.copy()
    F, F_prevstep = 0.0, 0.0
    dF = F_start
    hist = dict(F=[0.0], ep=[0.0], vm=[0.0], s1=[0.0], ux=[0.0], iters=[0])
    fnorm = np.linalg.norm(f_unit[mesh.free])
    collapsed = False
    snap = None
    t0 = time.time()

    while F_stop > F:
        F_try = min(F + dF, F_stop)
        # linear extrapolation predictor
        if F - F_prevstep > 0:
            u_try = u + (u - u_prev) * (F_try - F) / (F - F_prevstep)
        else:
            u_try = u * (F_try / F) if F > 0 else u.copy()
        ok = False
        for it in range(1, maxit + 1):
            eps = mesh.strains(u_try).reshape(-1, 3)
            sig, epsp_new, ebar_new, Dt = mat.update(eps, epsp, ebar)
            fint = mesh.internal_force(sig.reshape(4, mesh.nel, 3))
            r = (fint - F_try * f_unit)[mesh.free]
            if not np.all(np.isfinite(r)):
                break
            if np.linalg.norm(r) < tol * F_try * fnorm:
                ok = True
                n_iter = it
                break
            if not np.all(np.isfinite(Dt)):
                break
            K = mesh.stiffness(Dt.reshape(4, mesh.nel, 3, 3))
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', spla.MatrixRankWarning)
                    du = spla.spsolve(K, -r)
            except Exception:
                break
            if not np.all(np.isfinite(du)):
                break
            u_try[mesh.free] += du
        if not ok:
            dF *= 0.5
            if dF < 1e-3 * max(F, 1.0):
                collapsed = True
                break
            continue
        # accept
        u_prev, F_prevstep = u, F
        u, F = u_try, F_try
        epsp, ebar = epsp_new, ebar_new
        sig4 = sig.reshape(4, mesh.nel, 3)
        hist['F'].append(F)
        hist['ep'].append(ebar.max())
        hist['vm'].append(von_mises(sig4).max())
        hist['s1'].append(max_principal(sig4).max())
        hist['ux'].append(u[2 * mesh.centre_node])
        hist['iters'].append(n_iter)
        snap = dict(F=F, ebar=ebar.reshape(4, mesh.nel).max(axis=0).reshape(mesh.shape2d),
                    vm=von_mises(sig4).max(axis=0).reshape(mesh.shape2d))
        if verbose:
            print(f"   F = {F:7.1f} N   max ep = {ebar.max():.4f}   "
                  f"max vM = {hist['vm'][-1]:6.1f} MPa   Newton its = {n_iter}")
        if stop_ep is not None and ebar.max() >= stop_ep:
            break
        dF = min(dF * (1.4 if n_iter <= 5 else 0.7), dFmax)
    if verbose:
        print(f"   ({time.time() - t0:.1f} s)")
    return {k: np.array(v) for k, v in hist.items()}, snap, collapsed


def crossing(x, y, level):
    """First x where y crosses `level` (linear interpolation), else None."""
    idx = np.where(y >= level)[0]
    if idx.size == 0:
        return None
    i = idx[0]
    if i == 0:
        return x[0]
    return x[i - 1] + (level - y[i - 1]) * (x[i] - x[i - 1]) / (y[i] - y[i - 1])


# ============================================================================
# Squeeze factor -> contact size
# ============================================================================
def contact_diameter(R, t, sf, model='plastic'):
    """Contact diameter of a hemispherical tip (radius R) pressed into the
    sheet. SF = tool-tip gap / sheet thickness; both tools indent equally,
    each by delta = t (1 - SF) / 2.
      plastic: geometric chord   a = sqrt(2 R delta - delta^2)
      elastic: Hertz             a = sqrt(R delta)   (sink-in, smaller)"""
    delta = t * (1 - sf) / 2
    if delta <= 0:
        return 0.0
    a = np.sqrt(2 * R * delta - delta ** 2) if model == 'plastic' else np.sqrt(R * delta)
    return 2 * a


def run_case(a, d, t_patch, verbose):
    """Elastic + (optionally) plastic tear force for one contact size."""
    mesh = Mesh(a.D, d, a.t, a.n_patch, a.growth)
    if t_patch < a.t:
        mesh.thin_patch(a.shape, t_patch)
    f_unit = mesh.load_vector(a.shape, a.dist, 2.0)               # 1 N per tool
    out = dict(d=d, t_patch=t_patch, mesh=mesh)
    el = elastic_unit(mesh, a.E, a.nu, f_unit)
    out['el'] = el
    out['F_el'] = a.uts / max(el['vm'].max(), el['s1'].max())
    out['F_neck'] = out['F_frac'] = out['F_coll'] = None
    out['hist'] = out['snap'] = None
    if a.model in ('plastic', 'both'):
        mat = J2PlaneStress(a.E, a.nu, a.hardening, a.sy, a.uts, a.n)
        out['mat'] = mat
        F_y = (mat.sy0 if a.hardening == 'perfect' else a.sy) / el['vm'].max()
        stop_ep = 1.05 * max(mat.ep_neck, a.eps_f or 0) if a.hardening == 'swift' else None
        hist, snap, collapsed = plastic_ramp(mesh, mat, f_unit, F_start=0.95 * F_y,
                                             F_stop=20 * F_y, dFmax=0.08 * F_y,
                                             stop_ep=stop_ep, verbose=verbose)
        out['hist'], out['snap'] = hist, snap
        if a.hardening == 'swift':
            out['F_neck'] = crossing(hist['F'], hist['ep'], mat.ep_neck)
            if a.eps_f:
                out['F_frac'] = crossing(hist['F'], hist['ep'], a.eps_f)
        elif collapsed:
            out['F_coll'] = hist['F'][-1]
    return out


def design_force(c, a):
    """Tear force used for the mu_max curves: plastic criterion if available."""
    for k in ('F_neck', 'F_coll'):
        if c[k] is not None:
            return c[k], {'F_neck': 'local necking', 'F_coll': 'plastic collapse'}[k]
    return c['F_el'], 'elastic, peak stress = UTS'


# ============================================================================
def parse_args(argv=None):
    """Parse CLI options and fill unset material values from the preset."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_argument_group('geometry / contact')
    g.add_argument('--D', type=float, default=200.0, help='sheet side [mm]')
    g.add_argument('--t', type=float, default=1.0, help='sheet thickness [mm]')
    g.add_argument('--R', type=float, default=5.0, help='hemispherical tool tip radius [mm]')
    g.add_argument('--sf', type=str, default='0.8,0.85,0.9,0.95',
                   help='squeeze factor(s) = tool gap / t, comma-separated, each < 1')
    g.add_argument('--contact_model', choices=['plastic', 'elastic'], default='plastic',
                   help='contact radius from geometric chord (plastic) or Hertz (elastic)')
    g.add_argument('--d', type=float, default=None,
                   help='fixed contact size [mm]; overrides --sf/--R, no thinning')
    g.add_argument('--shape', choices=['circle', 'square'], default='circle')
    g.add_argument('--dist', choices=['hertz', 'uniform'], default='hertz')
    m = ap.add_argument_group('material (preset; any explicit value overrides it)')
    m.add_argument('--material', choices=sorted(MATERIALS), default='aa3003-o')
    m.add_argument('--E', type=float, default=None, help="Young's modulus [MPa]")
    m.add_argument('--nu', type=float, default=None)
    m.add_argument('--uts', type=float, default=None, help='engineering UTS [MPa]')
    m.add_argument('--sy', type=float, default=None, help='initial yield [MPa]')
    m.add_argument('--n', type=float, default=None, help='hardening exponent')
    m.add_argument('--hardening', choices=['swift', 'perfect'], default='swift')
    m.add_argument('--eps_f', type=float, default=None,
                   help='optional ductile-fracture equivalent plastic strain')
    s = ap.add_argument_group('solution / output')
    s.add_argument('--model', choices=['elastic', 'plastic', 'both'], default='both')
    s.add_argument('--n_patch', type=int, default=16, help='elements across the patch')
    s.add_argument('--growth', type=float, default=1.15, help='mesh grading ratio')
    s.add_argument('--Fn_min', type=float, default=100.0, help='normal force range start [N]')
    s.add_argument('--Fn_max', type=float, default=2000.0, help='normal force range end [N]')
    s.add_argument('--verbose', action='store_true', help='print every load step')
    s.add_argument('--no_plot', action='store_true')
    a = ap.parse_args(argv)
    for key, val in MATERIALS[a.material].items():
        if getattr(a, key) is None:
            setattr(a, key, val)
    return a


def main():
    np.seterr(all='ignore')
    a = parse_args()
    paths = study_paths(__file__)

    # ---- cases: (label, sf, d, t_patch)
    cases_in = []
    if a.d is not None:
        cases_in.append(('fixed d', None, a.d, a.t))
    else:
        for sf in [float(v) for v in a.sf.split(',')]:
            if sf >= 1:
                print(f"skipping SF = {sf:g}: no squeeze, so no indentation contact "
                      "(and the supporting tool may lose contact; "
                      "the symmetric model does not apply)")
                continue
            d = contact_diameter(a.R, a.t, sf, a.contact_model)
            cases_in.append((f'SF {sf:g}', sf, d, sf * a.t))
    if not cases_in:
        raise SystemExit('no valid cases')

    print("\n=== DSIF friction tear estimate ===")
    print(f"Material {a.material}: E={a.E:g}, nu={a.nu}, UTS={a.uts:g}, "
          f"yield={a.sy:g} MPa, n={a.n}")
    print(f"Sheet {a.D:g} x {a.D:g} x {a.t:g} mm | tool tip R = {a.R:g} mm | "
          f"{a.shape} patch, {a.dist} traction | contact model: {a.contact_model}")
    if a.hardening == 'swift' and a.model != 'elastic':
        mat = J2PlaneStress(a.E, a.nu, a.hardening, a.sy, a.uts, a.n)
        print(f"Swift fit: K = {mat.K:.1f} MPa, eps0 = {mat.e0:.5f}; "
              f"necking at ep = {mat.ep_neck:.3f} (true UTS {mat.true_uts:.1f} MPa)")

    cases = []
    for label, sf, d, tp in cases_in:
        t0 = time.time()
        print(f"\n-- {label}: contact d = {d:.3f} mm, thickness under tool = {tp:.3f} mm "
              f"(d/t = {d / a.t:.2f})", flush=True)
        if d / a.t < 1.5:
            print("   note: d/t < 1.5, membrane theory is rough here")
        c = run_case(a, d, tp, a.verbose)
        c['label'], c['sf'] = label, sf
        cases.append(c)
        print(f"   done in {time.time() - t0:.0f} s")

    # ---- summary table
    print("\nCritical tangential (friction) force PER TOOL [N]:")
    hdr = f"{'case':>10} {'d [mm]':>7} {'t_tool':>7} {'elastic':>9}"
    if a.model != 'elastic':
        hdr += f" {'necking':>9}" if a.hardening == 'swift' else f" {'collapse':>9}"
        if a.eps_f:
            hdr += f" {'eps_f':>9}"
    print(hdr)

    def fmt(v):
        return f"{v:9.1f}" if v is not None else f"{'-':>9}"

    for c in cases:
        row = f"{c['label']:>10} {c['d']:7.3f} {c['t_patch']:7.3f} {fmt(c['F_el'])}"
        if a.model != 'elastic':
            row += fmt(c['F_neck'] if a.hardening == 'swift' else c['F_coll'])
            if a.eps_f:
                row += fmt(c['F_frac'])
        print(row)

    # ---- mu_max as a function of normal force per tool
    Fn = np.linspace(a.Fn_min, a.Fn_max, 200)
    nice = np.array([100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000], float)
    Fn_tab = nice[(nice >= a.Fn_min) & (nice <= a.Fn_max)]
    if Fn_tab.size < 3:
        Fn_tab = np.linspace(a.Fn_min, a.Fn_max, 6)
    crit_name = design_force(cases[0], a)[1]
    print(f"\nmu_max = F_t,crit / F_n  (criterion: {crit_name}); keep mu BELOW these values")
    print(f"{'F_n [N]':>10}" + ''.join(f"{c['label']:>10}" for c in cases))
    for fn in Fn_tab:
        print(f"{fn:10.0f}" + ''.join(f"{design_force(c, a)[0] / fn:10.3f}" for c in cases))

    csv = paths['results'] / 'dsif_mu_vs_Fn.csv'
    cols = ['F_n_N'] + [f"mu_max_{c['label'].replace(' ', '')}" for c in cases]
    data = np.column_stack([Fn] + [design_force(c, a)[0] / Fn for c in cases])
    np.savetxt(csv, data, delimiter=',', header=','.join(cols), comments='', fmt='%.5g')
    print(f"\nSaved mu_max(F_n) table -> {csv}")

    if a.no_plot:
        return

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle

    apply_style()

    # ordinal one-hue ramp (validated light->dark), one step per case
    RAMP = ['#86b6ef', '#6da7ec', '#3987e5', '#2a78d6', '#1c5cab', '#184f95', '#104281', '#0d366b']
    idx = np.round(np.linspace(0, len(RAMP) - 1, len(cases))).astype(int) if len(cases) > 1 else [3]
    colors = [RAMP[i] for i in idx]

    # Figure 1: tear force vs SF, and mu_max vs F_n
    sweep = cases[0]['sf'] is not None and len(cases) > 1
    fig, axes = plt.subplots(1, 2 if sweep else 1, figsize=(13 if sweep else 7, 5),
                             constrained_layout=True, squeeze=False)
    axes = axes[0]
    ax_mu = axes[-1]
    for c, col in zip(cases, colors, strict=True):
        F_t, _ = design_force(c, a)
        mu = F_t / Fn
        label = f"{c['label']}  (d = {c['d']:.2f} mm, F_t = {F_t:.0f} N)"
        ax_mu.plot(Fn, mu, lw=2, color=col, label=label)
    ax_mu.set_xlim(a.Fn_min, a.Fn_max)
    ax_mu.set_ylim(0, 1.5)
    ax_mu.set_xlabel('Normal force per tool, F_n [N]')
    ax_mu.set_ylabel('Max allowable friction coeff., mu_max')
    ax_mu.set_title(f'mu_max vs normal force ({crit_name})', fontsize=11)
    ax_mu.legend(frameon=False, fontsize=9, title='squeeze factor', title_fontsize=9)
    if sweep:
        ax = axes[0]
        sfs = [c['sf'] for c in cases]
        ax.plot(sfs, [c['F_el'] for c in cases], lw=2, marker='o', ms=8, color='#2a78d6',
                label='elastic, peak stress = UTS')
        if a.model != 'elastic':
            key = 'F_neck' if a.hardening == 'swift' else 'F_coll'
            ax.plot(sfs, [c[key] if c[key] is not None else np.nan for c in cases], lw=2,
                    marker='o', ms=8, color='#eb6834',
                    label='elastoplastic, ' + ('local necking' if key == 'F_neck' else 'collapse'))
        ax.set_xlabel('Squeeze factor SF = tool gap / t')
        ax.set_ylabel('Tear force per tool, F_t,crit [N]')
        ax.set_title(f'Tearing force vs squeeze (R = {a.R:g} mm, t = {a.t:g} mm)', fontsize=11)
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False, fontsize=9)
    save_figure(fig, paths['figures'] / 'dsif_mu_vs_Fn')
    print(f"Saved plot -> {paths['figures'] / 'dsif_mu_vs_Fn'}.png")

    # Figure 2: field detail for the middle case
    c = cases[len(cases) // 2]
    mesh, el = c['mesh'], c['el']
    zoom = 3 * c['d']
    plastic = c['snap'] is not None
    fig, axes = plt.subplots(1, 2 if plastic else 1, figsize=(12 if plastic else 6.5, 4.8),
                             constrained_layout=True, squeeze=False)
    axes = axes[0]

    def outline(ax):
        if a.shape == 'circle':
            ax.add_patch(Circle((0, 0), c['d'] / 2, fill=False, ec='#222222', lw=1, ls='--'))
        else:
            ax.add_patch(Rectangle((-c['d'] / 2, -c['d'] / 2), c['d'], c['d'], fill=False,
                                   ec='#222222', lw=1, ls='--'))

    pc = axes[0].pcolormesh(mesh.xs, mesh.ys, el['vm'] * c['F_el'],
                            cmap='Blues', vmin=0, vmax=a.uts)
    axes[0].set_title(f"{c['label']}: elastic von Mises at F_t = {c['F_el']:.0f} N", fontsize=11)
    fig.colorbar(pc, ax=axes[0], label='MPa', shrink=0.85)
    if plastic:
        pc = axes[1].pcolormesh(mesh.xs, mesh.ys, c['snap']['ebar'], cmap='Blues', vmin=0)
        axes[1].set_title(
            f"{c['label']}: equivalent plastic strain at F_t = {c['snap']['F']:.0f} N",
            fontsize=11)
        fig.colorbar(pc, ax=axes[1], label='ep [-]', shrink=0.85)
    for ax in axes:
        outline(ax)
        ax.grid(False)
        for spine in ax.spines.values():   # full frame for field plots
            spine.set_visible(True)
        ax.set_xlim(-zoom, zoom)
        ax.set_ylim(-zoom, zoom)
        ax.set_aspect('equal')
        ax.set_xlabel('x [mm] (drag direction)')
        ax.set_ylabel('y [mm]')
    save_figure(fig, paths['figures'] / 'dsif_friction_limit')
    print(f"Saved plot -> {paths['figures'] / 'dsif_friction_limit'}.png")


if __name__ == '__main__':
    main()
