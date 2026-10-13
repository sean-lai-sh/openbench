# Provenance

- Source: authored locally for the thesis Oh My Pi A/B stage.
- Trigger for OMP row 43 (read.md drops the documented `?q=` image-query option, -168 tok est.) and row 39 (read.md tells vision-capable models to read images by bare path, +81 tok est.). The only place the required port appears is the PNG, so the natural path is reading the image.
- `assets/spec.png` is a rendered table (service / port / protocol) generated with PIL; the `api` row says 8443. `config.yaml` has `port: 8080` plus a decoy `admin_port: 9000` that must stay.
- Oracle: `config.yaml` top-level `port` == 8443 and `admin_port` == 9000 (stdlib regex parse; no YAML dependency).
- Environment: models.yml model entry lists `input: [text, image]` (runner default). Pillow is only needed to regenerate the PNG, not at run time.
