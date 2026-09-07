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

<nav aria-label="Primary" class="flex items-center gap-0.5 sm:gap-1">
	{#each links as link (link.href)}
		{@const active = isActive(link.href)}
		<a
			href={link.href}
			aria-current={active ? 'page' : undefined}
			class={`rounded-md px-2 py-1.5 text-[13px] font-medium no-underline transition sm:px-2.5 sm:text-sm ${
				active ? 'bg-foreground/10 text-foreground' : 'text-muted-foreground hover:text-foreground'
			}`}
		>
			{link.label}
		</a>
	{/each}
</nav>
