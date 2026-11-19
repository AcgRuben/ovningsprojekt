import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";

const sessionsDir = path.resolve("sessions");
fs.mkdirSync(sessionsDir, { recursive: true });

let gitStatus = "";
let lastCommit = "";
try {
  gitStatus = execSync("git status --short", { encoding: "utf8" }).trim();
  lastCommit = execSync("git log -1 --oneline", { encoding: "utf8" }).trim();
} catch {
  gitStatus = "Kunde inte läsa git status";
}

const checkpoint = [
  `# Automatisk sessionscheckpunkt (${new Date().toISOString()})`,
  `- Senaste commit: ${lastCommit || "inga commits"}`,
  `- Ocommittade filer:\n${gitStatus || "  (rent arbetsområde)"}`,
  `\nKom ihåg att uppdatera dagens fullständiga sessionslogg i sessions/ innan du avslutar helt.`,
].join("\n");

fs.writeFileSync(path.join(sessionsDir, ".latest-checkpoint.md"), checkpoint, "utf8");
