import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import console from "node:console";

const sessionsDir = path.resolve("sessions");
if (!fs.existsSync(sessionsDir)) process.exit(0);

const files = fs
  .readdirSync(sessionsDir)
  .filter((f) => f.endsWith(".md"))
  .sort();

if (files.length === 0) process.exit(0);

const latest = files[files.length - 1];
const content = fs.readFileSync(path.join(sessionsDir, latest), "utf8");

console.log(`=== SENASTE SESSIONSLOGG (${latest}) ===\n${content}\n=== SLUT PÅ SESSIONSLOGG ===`);
