<script lang="ts">
	import { page } from '$app/state';

	const links = [
		{ href: '/', label: 'Downloads' },
		{ href: '/torrents', label: 'Torrents' }
	];

	function isActive(href: string) {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<nav aria-label="Primary" class="flex items-center gap-1">
	{#each links as link (link.href)}
		{@const active = isActive(link.href)}
		<a
			href={link.href}
			aria-current={active ? 'page' : undefined}
			class={`rounded-md px-2.5 py-1.5 text-sm font-medium no-underline transition ${
				active ? 'bg-foreground/10 text-foreground' : 'text-muted-foreground hover:text-foreground'
			}`}
		>
			{link.label}
		</a>
	{/each}
</nav>
