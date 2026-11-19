import fs from "node:fs";
import process from "node:process";
import console from "node:console";

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const toolInput = input.tool_input || {};
const filePath = toolInput.file_path || "";
const newContent = toolInput.content || toolInput.new_string || "";

const isTestFile = /\.(test|spec)\.(ts|js|py)$|^tests\//.test(filePath.replace(/\\/g, "/"));

if (isTestFile) {
  if (/\b(it|test|describe)\.(skip|only)\b|@pytest\.mark\.skip/.test(newContent)) {
    console.error(
      "STOPP (Regel i docs/standard.md): Du får inte hoppa över (.skip) eller isolera (.only) tester. Åtgärda implementationen så att testet blir grönt istället.",
    );
    process.exit(2);
  }
  if (toolInput.content !== undefined && newContent.trim().length < 20) {
    console.error(
      "STOPP (Regel i docs/standard.md): Du får inte tömma eller ta bort innehållet i en testfil.",
    );
    process.exit(2);
  }
}
