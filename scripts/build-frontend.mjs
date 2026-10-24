// Prepara la interfaz para el .exe: copia frontend/ a build/frontend-dist/, ofusca el JS propio
// y minifica el CSS, de modo que lo que viaja dentro del instalador no se pueda leer cómodamente.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import JavaScriptObfuscator from "javascript-obfuscator";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = path.join(root, "frontend");
const out = path.join(root, "build", "frontend-dist");

fs.rmSync(out, { recursive: true, force: true });
fs.cpSync(src, out, { recursive: true });
fs.rmSync(path.join(out, "instances.json"), { force: true });   // solo lo usa el motor

const OWN_JS = ["app.js", "tauri-bridge.js"];
for (const name of OWN_JS) {
  const file = path.join(out, name);
  const code = fs.readFileSync(file, "utf8");
  const result = JavaScriptObfuscator.obfuscate(code, {
    compact: true,
    simplify: true,
    identifierNamesGenerator: "hexadecimal",
    renameGlobals: false,            // el HTML y los eventos usan nombres globales
    stringArray: true,
    stringArrayEncoding: ["rc4"],
    stringArrayThreshold: 1,
    stringArrayRotate: true,
    stringArrayShuffle: true,
    stringArrayWrappersCount: 2,
    stringArrayWrappersType: "function",
    splitStrings: true,
    splitStringsChunkLength: 6,
    transformObjectKeys: false,
    controlFlowFlattening: false,    // más rápido y pequeño; el resto ya lo vuelve ilegible
    deadCodeInjection: false,
    numbersToExpressions: true,
    unicodeEscapeSequence: false,
    sourceMap: false,
  });
  fs.writeFileSync(file, result.getObfuscatedCode());
  console.log("ofuscado", name);
}

const css = path.join(out, "style.css");
fs.writeFileSync(
  css,
  fs.readFileSync(css, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\s+/g, " ")
    .replace(/\s*([{};,>])\s*/g, "$1")
    .replace(/;}/g, "}"),
);
console.log("Interfaz lista en", out);
