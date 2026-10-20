/** Cadre façon fenêtre d'application (points décoratifs + titre), comme les maquettes de gitnimble.com. */
export default function Window({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`card overflow-hidden ${className}`}>
      <div className="flex items-center gap-2 border-b border-grid px-4 py-3" aria-hidden>
        <span className="h-3 w-3 rounded-full bg-[#ff5f57]" />
        <span className="h-3 w-3 rounded-full bg-[#febc2e]" />
        <span className="h-3 w-3 rounded-full bg-[#28c840]" />
        <span className="ml-3 truncate text-xs text-muted">{title}</span>
      </div>
      {children}
    </div>
  );
}
