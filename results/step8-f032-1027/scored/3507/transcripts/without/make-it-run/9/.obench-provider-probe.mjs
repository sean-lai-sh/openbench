import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname } from "node:path";
const cache = "/tmp/obench-cell-173ie01h/opencode_home_4q_lwes6/.cache/opencode";
const require = createRequire(import.meta.url);
let printed = "";
function versionOf(pkgJson) {
  try {
    const pkg = JSON.parse(readFileSync(pkgJson, "utf8"));
    return String(pkg.version || "");
  } catch {
    return "";
  }
}
function emit(version, dir) {
  if (!version || printed === version + "\n" + dir) return;
  printed = version + "\n" + dir;
  console.error(
    "OBENCH_PROVIDER_LOADED pkg=@ai-sdk/anthropic version=" + version +
      " path=" + dir,
  );
}
function loaderFor(file) {
  return file.endsWith(".json") ? "json" : "js";
}
try {
  if (typeof Bun !== "undefined" && typeof Bun.plugin === "function") {
    Bun.plugin({
      name: "obench-provider-probe",
      setup(build) {
        build.onResolve({ filter: /^@ai-sdk\/anthropic/ }, (args) => {
          let resolved = "";
          try {
            resolved = require.resolve(args.path, {
              paths: [cache, args.importer || cache],
            });
          } catch {}
          if (!resolved) {
            try { resolved = Bun.resolveSync(args.path, cache); } catch {}
          }
          console.error(
            "OBENCH_PROVIDER_RESOLVE pkg=@ai-sdk/anthropic path=" +
              (resolved || args.path),
          );
        });
        build.onLoad({
          filter: /\/node_modules\/@ai-sdk\/anthropic\/.*\.(?:mjs|cjs|js|json)$/,
        }, (args) => {
          const text = readFileSync(args.path, "utf8");
          const loader = loaderFor(args.path);
          if (loader === "js") {
            try {
              const pkgJson = require.resolve("@ai-sdk/anthropic/package.json", {
                paths: [dirname(args.path), cache],
              });
              emit(versionOf(pkgJson), dirname(pkgJson));
            } catch {}
          }
          return { contents: text, loader };
        });
      },
    });
  }
} catch {}
