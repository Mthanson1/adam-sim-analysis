#!/usr/bin/env python3
"""Mesh convergence check for dsif_friction_limit.py.

Reruns every squeeze factor at several patch resolutions (--n_patch) and reports
how the elastic and necking tear forces change as the mesh is refined.

    python mesh_convergence.py                       # n_patch 8,12,16,24
    python mesh_convergence.py --n_patch 8,16,32 --jobs 2
    python mesh_convergence.py --replot                # redraw figure from CSV

Outputs:
  results/mesh_convergence.csv
  results/figures/mesh_convergence.png
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

from adam_common import apply_style, save_figure, study_paths  # noqa: E402

SF_DEFAULT = (0.8, 0.85, 0.9, 0.95)


def run_one(job):
    sf, n_patch = job
    np.seterr(all='ignore')
    a = dsif.parse_args(['--n_patch', str(n_patch)])
    d = dsif.contact_diameter(a.R, a.t, sf, a.contact_model)
    t0 = time.time()
    c = dsif.run_case(a, d, sf * a.t, verbose=False)
    return dict(sf=sf, n_patch=n_patch, d=d, h=d / n_patch, nel=c['mesh'].nel,
                F_el=c['F_el'],
                F_neck=c['F_neck'] if c['F_neck'] is not None else float('nan'),
                seconds=time.time() - t0)


def print_table(rows):
    print(f"{'SF':>5} {'n_patch':>7} {'h [mm]':>7} {'elems':>6} {'F_el':>7} {'d%':>6} "
          f"{'F_neck':>7} {'d%':>6} {'time':>6}")
    for r in rows:
        print(f"{r['sf']:5.2f} {r['n_patch']:7d} {r['h']:7.4f} {r['nel']:6d} "
              f"{r['F_el']:7.1f} {r['dF_el_pct']:+6.1f} {r['F_neck']:7.1f} "
              f"{r['dF_neck_pct']:+6.1f} {r['seconds']:5.0f}s")


def read_csv(path):
    with open(path, newline='') as fh:
        rows = list(csv.DictReader(fh))
    ints = ('n_patch', 'nel')
    return [{k: int(v) if k in ints else float(v) for k, v in r.items()} for r in rows]


def plot(rows, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    apply_style()
    sf_list = sorted({r['sf'] for r in rows})
    n_list = sorted({r['n_patch'] for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), layout='constrained')
    colors = ['#86b6ef', '#3987e5', '#1c5cab', '#0d366b']
    for sf, col in zip(sf_list, colors, strict=False):
        sel = [r for r in rows if r['sf'] == sf]
        n = [r['n_patch'] for r in sel]
        axes[0].plot(n, [r['F_neck'] for r in sel], marker='o', lw=2, color=col,
                     label=f'SF {sf:g}')
        axes[1].plot(n, [r['F_el'] for r in sel], marker='o', lw=2, color=col)
    for ax, name in zip(axes, ('necking (design value)', 'elastic, peak stress = UTS'),
                        strict=True):
        ax.set_xticks(n_list)
        ax.set_xlabel('Elements across contact patch, n_patch')
        ax.set_ylabel('Tear force per tool, F_t,crit [N]')
        ax.set_title(f'Mesh convergence: {name}', fontsize=11)
    fig.legend(loc='outside right center', frameon=False, fontsize=9)
    save_figure(fig, path)
    print(f"Saved -> {path}.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n_patch', default='8,12,16,24', help='patch resolutions to test')
    ap.add_argument('--sf', default=','.join(map(str, SF_DEFAULT)))
    ap.add_argument('--jobs', type=int, default=4, help='parallel processes')
    ap.add_argument('--replot', action='store_true',
                    help='redraw the figure from the saved CSV without rerunning')
    args = ap.parse_args()
    paths = study_paths(__file__)
    csv_path = paths['results'] / 'mesh_convergence.csv'
    fig_path = paths['figures'] / 'mesh_convergence'

    if args.replot:
        rows = read_csv(csv_path)
        print_table(rows)
        plot(rows, fig_path)
        return

    n_list = sorted(int(v) for v in args.n_patch.split(','))
    sf_list = [float(v) for v in args.sf.split(',')]
    jobs = [(sf, n) for sf in sf_list for n in n_list]
    # Largest meshes first so the slowest jobs don't start last.
    jobs.sort(key=lambda j: -j[1])
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, job) for job in jobs]
        for fut in as_completed(futures):
            r = fut.result()
            rows.append(r)
            print(f"[{len(rows):2d}/{len(jobs)}] SF {r['sf']:g}, n_patch {r['n_patch']}: "
                  f"F_neck = {r['F_neck']:.1f} N ({r['seconds']:.0f} s)", flush=True)
    rows.sort(key=lambda r: (r['sf'], r['n_patch']))
    print(f"\n{len(rows)} runs in {time.time() - t0:.0f} s\n")

    # Change relative to the finest mesh for the same SF.
    finest = {r['sf']: r for r in rows if r['n_patch'] == n_list[-1]}
    for r in rows:
        ref = finest[r['sf']]
        r['dF_el_pct'] = 100 * (r['F_el'] / ref['F_el'] - 1)
        r['dF_neck_pct'] = 100 * (r['F_neck'] / ref['F_neck'] - 1)

    print_table(rows)
    with open(csv_path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved -> {csv_path}")
    plot(rows, fig_path)


if __name__ == '__main__':
    main()
