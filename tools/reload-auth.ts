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
 * Minimal shape of the credential store we reach through the runtime.
 * ModelRegistry is a synchronous facade over a private ModelRuntime; the
 * underlying pi-ai CredentialStore is what actually caches auth.json in
 * memory, so it's the thing that needs reload() to observe external edits.
 */
type CredentialStoreish = {
	reload?: () => void;
	store?: {
		reload?: () => void;
	};
	list?: () => Promise<ReadonlyArray<{ providerId: string }>>;
};

type Runtimeish = {
	credentials?: CredentialStoreish;
	listCredentials?: () => Promise<ReadonlyArray<{ providerId: string }>>;
};

/**
 * ModelRegistry keeps its ModelRuntime private, but the runtime owns the
 * credential store we need to reload. Reach it defensively so that an API
 * shape change degrades to "refresh only" instead of throwing.
 */
function getRuntime(ctx: ExtensionContext): Runtimeish | undefined {
	const runtime = (ctx.modelRegistry as unknown as { runtime?: Runtimeish }).runtime;
	return runtime ?? undefined;
}

/**
 * List provider IDs currently held in the runtime's in-memory credential store.
 */
async function listProviders(runtime: Runtimeish | undefined): Promise<string[]> {
	try {
		const list = runtime?.listCredentials ?? runtime?.credentials?.list;
		if (!list) return [];
		const entries = await list.call(runtime?.listCredentials ? runtime : runtime?.credentials);
		return entries.map((entry) => entry.providerId).sort();
	} catch {
		return [];
	}
}

/**
 * Reload the auth.json file, keeping track of what changed.
 */
async function reloadAuth(ctx: ExtensionContext, signature = getAuthFileSignature()): Promise<ReloadResult> {
	const runtime = getRuntime(ctx);
	const errors: string[] = [];

	// What we currently have in the in-memory credential store, reported to user.
	const providersBefore = await listProviders(runtime);

	// Re-read ~/.pi/agent/auth.json into the runtime's in-memory credential store.
	// RuntimeCredentials is just an overlay; the actual cached auth.json lives on
	// its underlying store.
	try {
		runtime?.credentials?.reload?.();
		runtime?.credentials?.store?.reload?.();
	} catch (error) {
		errors.push(formatError(error));
	}

	// Rebuild model availability and OAuth-derived model metadata from the
	// freshly loaded credentials. refresh() is async in this pi version.
	try {
		await ctx.modelRegistry.refresh();
	} catch (error) {
		errors.push(formatError(error));
	}

	// What we have now after reloading, again to report to user.
	const providersAfter = await listProviders(runtime);
	const modelsError = ctx.modelRegistry.getError();

	lastSeenAuthFile = signature;
	return { providersBefore, providersAfter, errors, modelsError };
}

async function reloadAuthIfChanged(ctx: ExtensionContext): Promise<void> {
	const signature = getAuthFileSignature();
	if (lastSeenAuthFile !== signature) {
		await reloadAuth(ctx, signature);
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
			const result = await reloadAuth(ctx);
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
		await reloadAuthIfChanged(ctx);
	});

	// We want to also refresh when an agent is in the middle of a loop
	// (e.g., calling tools), so we use turn_start as well, which is
	// *every* model turn.
	pi.on("turn_start", async (_event, ctx) => {
		await reloadAuthIfChanged(ctx);
	});
}
