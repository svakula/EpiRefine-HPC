# EpiRefine-HPC method

EpiRefine-HPC is a deterministic adaptive-mesh allocation workflow for a scalar
observable sampled over two in-plane epitaxial strains. It combines established
ideas from Delaunay interpolation, adaptive mesh refinement, maximin design, and
active sampling. The software packaging and provenance contract are specific to
this project; the underlying mathematical ideas should not be claimed as a new
class of sampling theory.

## Response mesh

For each crystallographic plane, accepted static calculations provide points

```text
p_i = (epsilon_a,i, epsilon_b,i),  m_i = measured observable.
```

The points are triangulated by a 2-D Delaunay triangulation. Within each triangle
the displayed response is the affine, piecewise-linear interpolant. No value is
invented outside the convex hull and a missing/failed calculation is not replaced
by zero.

For triangle `T`, define:

```text
h(T)       = longest edge length
Delta(T)   = max(m_i in T) - min(m_i in T)
g_proxy(T) = Delta(T) / h(T)
q(T)       = 4 sqrt(3) A(T) / sum_j length(edge_j)^2
```

`q` is a dimensionless shape screen: an equilateral triangle has `q=1`, while a
nearly collinear sliver approaches zero. A triangle is unresolved when it passes
the configured shape threshold, is larger than the target spatial resolution,
and either spans the configured response jump or crosses the configured low/high
response thresholds.

The boundary priority used by the implementation is

```text
score(T) = g_proxy(T) h(T) sqrt(q(T)).
```

This is an acquisition ranking, not an interpolation-error bound.

## New coordinates

Candidate coordinates are taken from a fixed barycentric grid strictly inside
each eligible triangle. The selected coordinate maximizes its distance to all
existing samples. Candidates must also satisfy the configured strain bounds and
minimum separation from both existing and newly selected points. This maximin
step improves local coverage without placing every calculation at an edge
midpoint or triangle centroid.

Low-response components are constructed on the measured Delaunay vertex graph.
A component is treated as an enclosed pocket only when it does not touch the
convex hull and every adjacent measured boundary vertex is at or above the high
threshold. Such a component receives a dedicated confirmation candidate before
remaining budget is spent on ranked unresolved triangles.

## Iteration and stopping

One iteration is:

```text
static results -> ingest -> plot -> propose -> relax -> static -> ingest
```

When ionic relaxation is unavailable, the alternative fixed-geometry protocol is:

```text
direct-static results -> ingest -> plot -> propose -> direct static -> ingest
```

These are distinct physical protocols, not interchangeable implementations of the
same observable. Every ingested row records `geometry_protocol`; comparisons and
interpolation should use one protocol at a time.

Thresholds, active planes, and budget should be frozen before viewing the new
outcomes. A plane can be removed from the active proposal list while remaining
visible as a stopped control in plots. Targeted samples diagnose and resolve the
feature that selected them, but they are not an unbiased validation set. If a
quantitative stopping error is needed, reserve model-blind holdout points before
response-driven selection.

Reasonable stopping statements are tied to declared criteria, for example: no
qualifying triangle remains above a 0.55 percentage-point diameter, an independent
error tolerance is met, or the predeclared compute budget is exhausted. “The
contour looks smooth” is not a sufficient stopping rule.

## HPC and provenance contract

Each proposed point records its source triangle and score. Relaxation inputs use
the nearest accepted geometry from the same plane, rescale only the first two
lattice vectors from source strain to target strain, preserve Direct coordinates
and the relaxed third vector, and record hashes. Statics are created only from
relaxations with explicit ionic-convergence and normal-termination evidence.
Only manifest-bound static OUTCARs enter the response surface.

Slurm submission is preview-only unless `--execute` is supplied. Numeric job
markers, scheduler working-directory reconciliation, sticky submission claims,
and existing-output checks prevent accidental duplicate jobs. The return archive
contains relative-path SHA-256 sums and excludes licensed POTCAR data.

## Geometry protocols

The default `relaxed_static` protocol first relaxes the internal/allowed structural
degrees of freedom at every target strain, then evaluates the observable with a static
calculation. This is the appropriate route when the desired response is that of the
locally relaxed epitaxial structure.

The optional `direct_static` protocol is a fixed-geometry response map. Starting from
the nearest accepted same-plane geometry, it applies the target in-plane deformation
to the first two lattice vectors,

```text
a_target = a_source (1 + epsilon_a,target) / (1 + epsilon_a,source)
b_target = b_source (1 + epsilon_b,target) / (1 + epsilon_b,source),
```

while preserving fractional coordinates and the third lattice vector. No ionic
relaxation is performed. It is useful when an rlxZ-style executable is unavailable or
when the fixed-geometry response is itself the intended model, but it cannot establish
the relaxed epitaxial response. For defensible interpolation, seed geometries must use
a consistent construction/reference convention and `direct_static` and
`relaxed_static` data must not be silently combined.

## Scientific scope

Run a separate map for each discrete interface termination, registry, thickness,
composition, magnetic initialization, and boundary condition. EpiRefine allocates
calculations within one such map; it does not determine the stable interface or
magnetic ground state. DFT convergence, finite-size effects, competing structures,
and experimental uncertainty remain outside the interpolation model and must be
assessed separately.
