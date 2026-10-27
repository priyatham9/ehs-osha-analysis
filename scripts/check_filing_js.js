// Read {"rules":..., "records":[...]} on stdin, print one result per record as JSON.
const { checkFiling } = require("../docs/filing_check.js");
let buf = "";
process.stdin.on("data", (d) => (buf += d));
process.stdin.on("end", () => {
  const { rules, records } = JSON.parse(buf);
  process.stdout.write(JSON.stringify(records.map((r) => checkFiling(r, rules))));
});
