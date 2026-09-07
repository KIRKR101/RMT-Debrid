import { fileURLToPath } from 'node:url';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	// Read the repo-root .env so the proxy follows a custom SERVER_PORT even
	// when vite is started with cwd set to frontend/ (which hides root .env).
	const rootEnv = loadEnv(mode, fileURLToPath(new URL('..', import.meta.url)), '');
	const backendTarget = `http://127.0.0.1:${Number(process.env.SERVER_PORT ?? rootEnv.SERVER_PORT ?? 8000)}`;

	return {
		plugins: [tailwindcss(), sveltekit()],
		server: {
			proxy: {
				'/api': backendTarget,
				'/ws': {
					target: backendTarget,
					ws: true
				}
			}
		}
	};
});
