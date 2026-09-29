# figma-view

English | [繁體中文](README.zh-TW.md)

A Claude Code plugin that reads layer specs and screenshots from the Figma web app, for when Figma MCP is out of quota or your account only has a View seat.

- **node-id mode**: give it a URL with a `node-id` and it reads that layer directly. Takes about 5 seconds, calls no model, and sends nothing to outside services.
- **Description mode**: describe the layer in words, and Jev (TypeSafe) searches and walks the layer tree to find it.

Available: Layout (size, radius, border, auto layout direction, Hug/Fill, Gap, padding), Typography, Colors (token name and hex), text content, and the parent component. Not available: CSS, variables.

## Install

```
/plugin marketplace add <org>/figma-view
/plugin install figma-view@figma-view
```

**Without the plugin system**: copy `plugins/figma-view/skills/inspect/` to `~/.claude/skills/figma-inspect/`. The skill menu then shows it as `/inspect`; `/figma-inspect` also works. You'll need to copy it again to get updates.

## Requirements

- `git` and [`uv`](https://docs.astral.sh/uv/)
- Chrome with the [Claude in Chrome](https://claude.com/chrome) extension, logged in to Figma in that profile
- On first use, Chrome shows "Allow remote debugging?". Click Allow
- Access to GitHub: on first use, it automatically downloads the open-source package [jev-ultrafast](https://github.com/browser-use/jev-ultrafast), which it uses to drive Chrome and call Jev. It goes in `~/.cache/jev-ultrafast` by default; set the `JEV_DIR` environment variable to put it elsewhere.
- Description mode needs the `TYPESAFE_API_KEY` environment variable. Without it, only node-id mode works

## Usage

Paste a Figma link into Claude Code and ask about its specs, or run `/figma-view:inspect <URL> [layer to find]`.

For the best results, right-click the layer in Figma → **Copy link to selection** and paste that node-id link. If you only have a description, wrap layer names in 「」 exactly as they appear in Figma, e.g. `the 「Frame 1234」 frame`.

Description mode occasionally picks the wrong layer; when it's unsure, the skill asks you to check the screenshot.

## Notes

- **Data sent out**: description mode sends your request, page names, and layer names to TypeSafe. Before using it, confirm your company allows sending design file content to outside services.
- **Read-only**: it only clicks pages, layers, expand carets, the search box, and the Properties tab. It never edits the file, shares it, or comments.
- The skill assumes a View seat (Dev Mode locked). If you have Dev Mode access, Figma MCP can give you more (CSS, variables).
