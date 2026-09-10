<script lang="ts">
	import { page } from '$app/state';

	const links = [
		{ href: '/', label: 'Downloads' },
		{ href: '/discover', label: 'Discover' },
		{ href: '/torrents', label: 'Torrents' }
	];

	function isActive(href: string) {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<nav aria-label="Primary" class="flex shrink-0 items-center gap-1.5 max-[419px]:gap-0">
	{#each links as link (link.href)}
		{@const active = isActive(link.href)}
		<a
			href={link.href}
			aria-current={active ? 'page' : undefined}
			class={`relative rounded-md px-2.5 py-2 text-[13px] whitespace-nowrap no-underline transition-colors focus-visible:outline-1 focus-visible:outline-offset-1 focus-visible:outline-ring max-[419px]:px-1.5 max-[359px]:px-1 sm:px-3.5 ${
				active
					? 'font-semibold text-foreground'
					: 'font-medium text-muted-foreground hover:text-foreground'
			}`}
		>
			{link.label}
			{#if active}
				<span class="absolute inset-x-2.5 -bottom-[9px] h-[2px] bg-foreground" aria-hidden="true"
				></span>
			{/if}
		</a>
	{/each}
</nav>
