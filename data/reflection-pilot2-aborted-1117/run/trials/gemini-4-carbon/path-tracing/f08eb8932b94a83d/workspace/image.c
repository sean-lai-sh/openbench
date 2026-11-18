#include <math.h>
#include <stdio.h>

typedef struct {
    float x, y, z;
} Vec3;

typedef struct {
    Vec3 orig, dir;
} Ray;

typedef struct {
    Vec3 center;
    float radius;
} Sphere;

typedef struct {
    float t;
    Vec3 point, normal;
    int hit;
} Hit;

static Vec3 vadd(Vec3 a, Vec3 b) { return (Vec3){a.x + b.x, a.y + b.y, a.z + b.z}; }
static Vec3 vsub(Vec3 a, Vec3 b) { return (Vec3){a.x - b.x, a.y - b.y, a.z - b.z}; }
static Vec3 vmul(Vec3 a, float s) { return (Vec3){a.x * s, a.y * s, a.z * s}; }
static float vdot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

static Vec3 vnorm(Vec3 a) {
    float l = sqrt(vdot(a, a));
    return (Vec3){a.x / l, a.y / l, a.z / l};
}

static Ray ray_create(Vec3 orig, Vec3 dir) {
    return (Ray){orig, vnorm(dir)};
}

static Vec3 ray_at(Ray r, float t) {
    return vadd(r.orig, vmul(r.dir, t));
}

static Hit sphere_intersect(Ray r, Sphere s) {
    Hit h = {0};
    Vec3 oc = vsub(r.orig, s.center);
    float a = vdot(r.dir, r.dir);
    float b = 2.0f * vdot(oc, r.dir);
    float c = vdot(oc, oc) - s.radius * s.radius;
    float disc = b * b - 4.0f * a * c;
    if (disc < 0.0f) return h;
    float t = (-b - sqrt(disc)) / (2.0f * a);
    if (t < 0.001f) {
        t = (-b + sqrt(disc)) / (2.0f * a);
        if (t < 0.001f) return h;
    }
    h.hit = 1;
    h.t = t;
    h.point = ray_at(r, t);
    h.normal = vnorm(vsub(h.point, s.center));
    return h;
}

static Hit plane_intersect(Ray r, float y) {
    Hit h = {0};
    if (fabsf(r.dir.y) < 0.0001f) return h;
    float t = (y - r.orig.y) / r.dir.y;
    if (t < 0.001f) return h;
    h.hit = 1;
    h.t = t;
    h.point = ray_at(r, t);
    h.normal = (Vec3){0.0f, 1.0f, 0.0f};
    return h;
}

static Vec3 trace(Ray r, Sphere s, Vec3 light_dir) {
    Hit sh = sphere_intersect(r, s);
    Hit ph = plane_intersect(r, -1.5f);
    Hit ch = {0};
    int hit_sphere = 0;
    if (sh.hit && (!ph.hit || sh.t < ph.t)) {
        ch = sh;
        hit_sphere = 1;
    } else if (ph.hit) {
        ch = ph;
    } else {
        float t = 0.5f * (r.dir.y + 1.0f);
        return vadd(vmul((Vec3){1.0f, 1.0f, 1.0f}, 1.0f - t), vmul((Vec3){0.5f, 0.7f, 1.0f}, t));
    }

    float diff = fmax(vdot(ch.normal, light_dir), 0.0);
    Vec3 shadow_orig = vadd(ch.point, vmul(ch.normal, 0.001f));
    if (sphere_intersect(ray_create(shadow_orig, light_dir), s).hit) {
        diff = 0.0f;
    }
    float ambient = 0.2f;
    float intensity = ambient + (1.0f - ambient) * diff;
    Vec3 base = hit_sphere
        ? (Vec3){1.0f, 0.2f, 0.2f}
        : ((((int)(floor(ch.point.x) + floor(ch.point.z)) & 1) == 0)
            ? (Vec3){0.9f, 0.9f, 0.9f}
            : (Vec3){0.4f, 0.4f, 0.4f});
    return vmul(base, intensity);
}

int main(void) {
    int w = 2400, h = 1800;
    Vec3 orig = {0.0f, 0.0f, 0.0f};
    float vh = 2.0f;
    float vw = vh * ((float)w / (float)h);
    Vec3 horiz = {vw, 0.0f, 0.0f};
    Vec3 vert = {0.0f, vh, 0.0f};
    Vec3 llc = vsub(vsub(vsub(orig, vmul(horiz, 0.5f)), vmul(vert, 0.5f)), (Vec3){0.0f, 0.0f, 1.0f});
    Sphere sphere = {{0.0f, -0.5f, -5.0f}, 1.0f};
    Vec3 light_dir = vnorm((Vec3){1.0f, 1.0f, -1.0f});

    FILE *f = fopen("reconstructed.ppm", "w");
    if (!f) return 1;
    fprintf(f, "P3\n%d %d\n255\n", w, h);
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            float u = (float)x / (float)(w - 1);
            float v = (float)y / (float)(h - 1);
            Vec3 dir = vadd(llc, vadd(vmul(horiz, u), vsub(vmul(vert, 1.0f - v), orig)));
            Vec3 c = trace(ray_create(orig, dir), sphere, light_dir);
            float cr = fmin(fmax(c.x, 0.0), 1.0);
            float cg = fmin(fmax(c.y, 0.0), 1.0);
            float cb = fmin(fmax(c.z, 0.0), 1.0);
            fprintf(f, "%d %d %d\n", (int)(255.99f * cr), (int)(255.99f * cg), (int)(255.99f * cb));
        }
    }
    fclose(f);
    return 0;
}
