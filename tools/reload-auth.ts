/**
 * @fileoverview This extension hot-reloads Pi's in-memory auth when
 * ~/.pi/agent/auth.json is updated by an external login/refresher. This lets
 * the current session keep running.
 *
 * Tries to be efficient by only reloading when the file has changed.
 *
 * Ryan Dale @daler
 */


import { statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const AUTH_PATH = join(getAgentDir(), "auth.json");

let lastSeenAuthFile: string | undefined;

/*
 * Make a string to represent the file state to detect changes
 */
function getAuthFileSignature(): string {
	try {
		const { mtimeMs, size } = statSync(AUTH_PATH);
		return `${mtimeMs}:${size}`;
	} catch (error) {
		if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT") {
			return "missing";
		}
		throw error;
	}
}

/**
 * Used for reporting back to the user what we did
 */
type ReloadResult = {
	providersBefore: string[];
	providersAfter: string[];
	errors: string[];
	modelsError?: string;
};

function formatError(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

/**
 * Reload the auth.json file, keeping track of what changed.
 */
function reloadAuth(ctx: ExtensionContext, signature = getAuthFileSignature()): ReloadResult {
	// AuthStorage handles loading, parsing, and error handling.
	// (We're only using AUTH_PATH above for checking if the file changed)
	const authStorage = ctx.modelRegistry.authStorage;

	// What we currently have in auth storage, will be reported to user
	const providersBefore = authStorage.list().sort();

	// Re-read ~/.pi/agent/auth.json into the in-memory AuthStorage instance.
	// If auth.json is invalid JSON, AuthStorage keeps the previous in-memory data
	// and records an error; report that through /auth-reload.
	authStorage.reload();

	// Rebuild model availability and OAuth-derived model metadata from the
	// freshly loaded credentials. E.g., if the updated auth.json has a new
	// provider, we want that to show up in the choices for /model.
	ctx.modelRegistry.refresh();

	// What we have now after reloading, again to report to user
	const providersAfter = authStorage.list().sort();
	const errors = authStorage.drainErrors().map(formatError);
	const modelsError = ctx.modelRegistry.getError();

	lastSeenAuthFile = signature;
	return { providersBefore, providersAfter, errors, modelsError };
}

function reloadAuthIfChanged(ctx: ExtensionContext): void {
	const signature = getAuthFileSignature();
	if (lastSeenAuthFile !== signature) {
		reloadAuth(ctx, signature);
	}
}

/*
 * Report back to user what we did
 */
function summarize(result: ReloadResult): string {
	const before = result.providersBefore.join(", ") || "none";
	const after = result.providersAfter.join(", ") || "none";
	const problems = [...result.errors, result.modelsError].filter(Boolean);
	if (problems.length > 0) {
		return `Reloaded auth.json with warnings. Providers: ${before} -> ${after}. ${problems.join("; ")}`;
	}
	return `Reloaded auth.json. Providers: ${before} -> ${after}.`;
}

export default function (pi: ExtensionAPI) {
	pi.registerCommand("auth-reload", {
		description: "Reload ~/.pi/agent/auth.json without restarting pi",
		handler: async (_args, ctx) => {
			const result = reloadAuth(ctx);
			ctx.ui.notify(summarize(result), result.errors.length || result.modelsError ? "warning" : "info");
		},
	});

	// The auth.json is already checked at initial startup, but we need to
	// check and update at some non-default events.
	//
	// Check just before each user prompt begins and before every provider turn.
	// The first check reloads once so an extension /reload can catch credentials
	// changed since pi started; later checks reload only when auth.json changed.
	//
	// before_agent_start triggers after the user submits a prompt and
	// before the agent starts its loop.
	pi.on("before_agent_start", async (_event, ctx) => {
		reloadAuthIfChanged(ctx);
	});

	// We want to also refresh when an agent is in the middle of a loop
	// (e.g., calling tools), so we use turn_start as well, which is
	// *every* model turn.
	pi.on("turn_start", async (_event, ctx) => {
		reloadAuthIfChanged(ctx);
	});
}
