---
description: Convert existing tasks into actionable, dependency-ordered GitHub issues for the feature based on available design artifacts.
argument-hint: [optional input]
---

You are executing the Spec Kit command **/speckit.taskstoissues** for the *Chronicle of the Velvet Lies* project.

IMPORTANT: This project's Spec Kit lives in the `chronicle/` subdirectory. Treat `chronicle/` as the working directory and repo/spec root for ALL Spec Kit relative paths (`.specify/`, `specs/`, `check-prerequisites.ps1`, etc.). The helper scripts are PowerShell (run them with `chronicle/` as the working directory). The git repository root is the parent `CHRONICLE/` folder.

Read the full, authoritative command instructions in @chronicle/.github/agents/speckit.taskstoissues.agent.md and execute every step in order. That file is the single source of truth — follow it exactly. Do not duplicate or summarize its logic; perform it.

User input (this is the `$ARGUMENTS` the instructions refer to):

$ARGUMENTS