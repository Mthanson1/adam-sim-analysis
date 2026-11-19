#!/usr/bin/env python3
"""Verification checks for dsif_friction_limit.py.

  kelvin   Elastic FE stresses vs the closed-form Kelvin solution for a point
           force in an infinite plate (plane stress). Checks the element,
           assembly and load implementation.
  domain   Tear forces at several sheet sizes D, to show the clamped edge is
           far enough away not to matter.

    python verification.py kelvin
    python verification.py domain --D 100,200,400
    python verification.py all

Outputs go to results/ (CSV) and results/figures/ (PNG).
"""

import os

# Must be set before numpy loads. Otherwise every worker process starts one BLAS
# thread per core, each with its own buffers, and parallel runs exhaust memory.
for _var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_var, '1')

import argparse  # noqa: E402
import csv  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402

import dsif_friction_limit as dsif  # noqa: E402
import numpy as np  # noqa: E402
import scipy.sparse.linalg as spla  # noqa: E402

from adam_common import apply_style, save_figure, study_paths  # noqa: E402

SF_DEFAULT = (0.8, 0.85, 0.9, 0.95)


def write_csv(rows, path):
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Saved -> {path}")


# ============================================================================
# Kelvin check
# ============================================================================
def kelvin_stresses(P, t, nu, x, y):
    """Plane-stress Kelvin solution: force P in +x at the origin of an infinite
    plate of thickness t. Returns sigma_xx, sigma_yy, tau_xy."""
    r = np.hypot(x, y)
    th = np.arctan2(y, x)
    k = P / (4 * np.pi * t * r)
    s_rr = -(3 + nu) * k * np.cos(th)
    s_tt = (1 - nu) * k * np.cos(th)
    s_rt = (1 - nu) * k * np.sin(th)
    c, s = np.cos(th), np.sin(th)
    sxx = s_rr * c**2 + s_tt * s**2 - 2 * s_rt * s * c
    syy = s_rr * s**2 + s_tt * c**2 + 2 * s_rt * s * c
    txy = (s_rr - s_tt) * s * c + s_rt * (c**2 - s**2)
    return sxx, syy, txy


def run_kelvin(paths, D=1000.0, d=2.0, t=1.0, n_patch=16):
    """Elastic solve with a small patch on a large plate, sampled at radii where
    the patch looks like a point load and the edge is still far away."""
    mat = dsif.MATERIALS['aa3003-o']
    E, nu = mat['E'], mat['nu']
    mesh = dsif.Mesh(D, d, t, n_patch, 1.15)
    f_unit = mesh.load_vector('circle', 'hertz', 2.0)
    P = 2.0                                     # both faces together
    C = dsif.dmat(E, nu)
    u = np.zeros(mesh.ndof)
    u[mesh.free] = spla.spsolve(mesh.stiffness(C), f_unit[mesh.free])
    sig = (mesh.strains(u) @ C.T).mean(axis=0)  # element-centre average, (nel, 3)

    rows = []
    for r_target in (2.5, 4, 6, 10, 15, 25, 40):
        for axis, (ux, uy), comp in (('x', (1, 0), 0), ('-x', (-1, 0), 0),
                                     ('y', (0, 1), 2)):
            # Element centre closest to the sample point on this axis.
            dist = np.hypot(mesh.xc - ux * r_target, mesh.yc - uy * r_target)
            e = np.argmin(dist)
            xe, ye = mesh.xc[e], mesh.yc[e]
            exact = kelvin_stresses(P, t, nu, xe, ye)[comp]
            rows.append(dict(axis=axis, component=['sxx', 'syy', 'txy'][comp],
                             r=float(np.hypot(xe, ye)), fe=float(sig[e, comp]),
                             exact=float(exact),
                             err_pct=float(100 * (sig[e, comp] / exact - 1))))

    print(f"\nKelvin check (D = {D:g} mm, d = {d:g} mm, P = {P:g} N, n_patch = {n_patch})")
    print(f"{'axis':>4} {'comp':>4} {'r [mm]':>7} {'FE [MPa]':>10} {'exact':>10} {'err':>7}")
    for r in rows:
        print(f"{r['axis']:>4} {r['component']:>4} {r['r']:7.2f} {r['fe']:10.5f} "
              f"{r['exact']:10.5f} {r['err_pct']:+6.1f}%")
    write_csv(rows, paths['results'] / 'verify_kelvin.csv')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter, ScalarFormatter

    apply_style()
    fig, ax = plt.subplots(figsize=(7, 4.5), layout='constrained')
    r_line = np.geomspace(2, 50, 100)
    # |sigma_xx| is the same ahead and behind, so one analytic line covers both.
    exact_sxx = np.abs(kelvin_stresses(P, t, nu, r_line, 0 * r_line)[0])
    exact_txy = np.abs(kelvin_stresses(P, t, nu, 0 * r_line, r_line)[2])
    ax.plot(r_line, exact_sxx, '-', color='#2a78d6', lw=1.5, label='Kelvin: |sigma_xx| on x-axis')
    ax.plot(r_line, exact_txy, '-', color='#eb6834', lw=1.5, label='Kelvin: |tau_xy| on y-axis')
    styles = {
        'x': dict(marker='o', ms=10, mfc='none', mec='#2a78d6', mew=1.5,
                  label='FE: sigma_xx ahead (+x, compression)'),
        '-x': dict(marker='o', ms=4, color='#0d366b',
                   label='FE: sigma_xx behind (-x, tension)'),
        'y': dict(marker='s', ms=6, color='#eb6834', label='FE: tau_xy flank (+y)'),
    }
    for axis, style in styles.items():
        sel = [r for r in rows if r['axis'] == axis]
        ax.plot([r['r'] for r in sel], [abs(r['fe']) for r in sel], ls='none', **style)
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xticks([2, 3, 5, 10, 20, 40])
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel('Distance from patch centre, r [mm]')
    ax.set_ylabel('|stress| per 1 N per tool [MPa]')
    ax.set_title('Elastic FE (points) vs Kelvin solution (lines)', fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    save_figure(fig, paths['figures'] / 'verify_kelvin')
    print(f"Saved -> {paths['figures'] / 'verify_kelvin'}.png")


# ============================================================================
# Domain size check
# ============================================================================
def run_domain_case(job):
    sf, D = job
    np.seterr(all='ignore')
    a = dsif.parse_args(['--D', str(D)])
    d = dsif.contact_diameter(a.R, a.t, sf, a.contact_model)
    t0 = time.time()
    c = dsif.run_case(a, d, sf * a.t, verbose=False)
    F_neck = c['F_neck'] if c['F_neck'] is not None else float('nan')
    return dict(sf=sf, D=D, nel=c['mesh'].nel, F_el=c['F_el'], F_neck=F_neck,
                seconds=time.time() - t0)


def run_domain(paths, D_list, sf_list, jobs):
    cases = [(sf, D) for sf in sf_list for D in D_list]
    rows = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_domain_case, c) for c in cases]
        for fut in as_completed(futures):
            r = fut.result()
            rows.append(r)
            print(f"[{len(rows):2d}/{len(cases)}] SF {r['sf']:g}, D {r['D']:g}: "
                  f"F_neck = {r['F_neck']:.1f} N ({r['seconds']:.0f} s)", flush=True)
    rows.sort(key=lambda r: (r['sf'], r['D']))
    ref = {r['sf']: r for r in rows if r['D'] == max(D_list)}
    for r in rows:
        r['dF_el_pct'] = 100 * (r['F_el'] / ref[r['sf']]['F_el'] - 1)
        r['dF_neck_pct'] = 100 * (r['F_neck'] / ref[r['sf']]['F_neck'] - 1)

    print(f"\nDomain size check ({len(rows)} runs in {time.time() - t0:.0f} s), "
          f"change relative to D = {max(D_list):g} mm")
    print(f"{'SF':>5} {'D [mm]':>7} {'elems':>6} {'F_el':>7} {'d%':>6} {'F_neck':>7} {'d%':>6}")
    for r in rows:
        print(f"{r['sf']:5.2f} {r['D']:7.0f} {r['nel']:6d} {r['F_el']:7.1f} "
              f"{r['dF_el_pct']:+6.2f} {r['F_neck']:7.1f} {r['dF_neck_pct']:+6.2f}")
    write_csv(rows, paths['results'] / 'verify_domain.csv')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('check', choices=['kelvin', 'domain', 'all'])
    ap.add_argument('--D', default='100,200,400', help='sheet sizes for the domain check [mm]')
    ap.add_argument('--sf', default=','.join(map(str, SF_DEFAULT)))
    ap.add_argument('--jobs', type=int, default=4, help='parallel processes (domain check)')
    args = ap.parse_args()
    np.seterr(all='ignore')
    paths = study_paths(__file__)

    if args.check in ('kelvin', 'all'):
        run_kelvin(paths)
    if args.check in ('domain', 'all'):
        run_domain(paths, [float(v) for v in args.D.split(',')],
                   [float(v) for v in args.sf.split(',')], args.jobs)


if __name__ == '__main__':
    main()
