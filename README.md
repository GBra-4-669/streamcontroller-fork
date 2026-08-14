# StreamDeckGB

A personal fork of [StreamController](https://github.com/StreamController/StreamController) with a handful of quality-of-life changes I use on my own Stream Deck.

![StreamDeckGB on the "beatiful" page](docs/streamdeckgb-beatiful.gif)

> **This is a private, unmaintained fork.** The repository is public only so I can use GitHub's tooling (Pages, Actions, and releases) for my own testing. Treat it as a snapshot of my working tree, not as software meant for general use.

- **No prebuilt binaries.** There is no installer and no release build.
- **No support.** This will almost certainly not run as-is on your machine; expect to read and modify the source to make it work on your own setup.
- **Use at your own risk.**.

All credit for the core application goes to the [StreamController](https://github.com/StreamController/StreamController) team. Please star, contribute to, and use the upstream project — not this one. This fork exists only to scratch a few personal itches on my own hardware.

## What's different from upstream

- **Background opacity**: opacity control for all backgrounds (page and key backgrounds), not just foreground images.
- **Layered images per key**: each key can hold two images, each with its own opacity, composited over the page background. For example: page background + one GIF + one icon per key.
- **Smart Command**: a new stateful action type. See the source for current behavior; it is actively evolving as I use it and has no stable spec.
- **Watch GitHub Deployments**: displays a repo's deployment status on a key. Press to refresh manually, or enable automatic updates via a local `pre-push` hook.
- **Static WebP support**: support for static `.webp` images as key and background assets.
- **GIF speed fix**: corrected a logic error in animated GIF playback that made GIFs play at the wrong speed relative to their frame delays.

## Tested on

- Arch Linux
- Fedora 44
- One Stream Deck model: the 5×3 grid

That is the full list. I have not tested other distributions, desktop environments, or Stream Deck models (Mini, XL, Pedal, and so on), and I have no idea how they will behave — including whether a model with more buttons has enough headroom for layered backgrounds. Do not assume you can run two GIFs plus a page background on every key without ever hitting limits.

## Not included / not planned

- No packaging, binaries, or installers.
- No CI guarantees and no release channel.
- No plans to upstream these changes. My personal requirements are too specific to my setup to be worth a pull request

## Installation

There is no installer or release build. To run this:

1. Clone the repository and build it.
2. Expect to patch things for your own distribution, desktop environment, and hardware. Paths, dependencies, and Stream Deck model handling have moved on upstream since this was forked, and this fork is not kept in sync.

## Why this exists

These are my daily-driver customizations for my own Stream Deck workflow — deployment status monitoring, layered backgrounds, and a few quality-of-life fixes — that are not necessarily a fit for upstream as they are. I keep them as a fork rather than a diff or patch file mostly because it makes tracking changes over time easier for me.

## Upstream project

Please use and support the real thing: [StreamController/StreamController](https://github.com/StreamController/StreamController) — actively maintained, with far more features, broader hardware support, and an actual community behind it.
