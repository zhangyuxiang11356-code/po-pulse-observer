import http from "node:http";
import { pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
import path from "node:path";
import fs from "node:fs";

function resolveParserPath() {
  const fromEnv = process.env.RSS_AGENT_VIEWER_PARSER_PATH;
  if (fromEnv && fs.existsSync(fromEnv)) {
    return fromEnv;
  }

  try {
    const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf-8" }).trim();
    const parserPath = path.join(npmRoot, "rss-agent-viewer", "dist", "core", "parser.js");
    if (fs.existsSync(parserPath)) {
      return parserPath;
    }
  } catch {}

  for (const parserPath of [
    "/usr/lib/node_modules/rss-agent-viewer/dist/core/parser.js",
    "/usr/local/lib/node_modules/rss-agent-viewer/dist/core/parser.js",
  ]) {
    if (fs.existsSync(parserPath)) {
      return parserPath;
    }
  }

  throw new Error("rss-agent-viewer parser.js not found");
}

const parserPath = resolveParserPath();
const { parseFeed } = await import(pathToFileURL(parserPath).href);
const host = process.env.RSS_AGENT_VIEWER_BRIDGE_HOST || "127.0.0.1";
const port = Number(process.env.RSS_AGENT_VIEWER_BRIDGE_PORT || "18789");

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname !== "/parse") {
      res.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: "not found" }));
      return;
    }

    const feedUrl = url.searchParams.get("url");
    const timeoutMs = Number(url.searchParams.get("timeout_ms") || "10000");
    if (!feedUrl) {
      res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: "missing url" }));
      return;
    }

    const parsed = await parseFeed(feedUrl, timeoutMs);
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(parsed));
  } catch (error) {
    res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ error: String(error?.message || error) }));
  }
});

server.listen(port, host, () => {
  console.log(`rss-agent-viewer bridge listening on http://${host}:${port}`);
});
