import { Badge } from "@/components/ui/badge"
import type {
  GraphObjectOpener,
  PhaseTopic,
  Translate,
} from "@/components/research-graph/model"

type BadgeVariant = "default" | "secondary" | "outline"

export default function TopicButton({
  topic,
  variant = "outline",
  showCount = false,
  onOpen,
  t,
}: {
  topic: PhaseTopic
  variant?: BadgeVariant
  showCount?: boolean
  onOpen: GraphObjectOpener
  t: Translate
}) {
  const visibleLabel = showCount
    ? `${topic.name} · ${topic.count}`
    : topic.name
  return (
    <button
      type="button"
      className="group inline-flex cursor-pointer rounded-md transition-transform hover:-translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
      aria-label={`${t("research_graph.open_topic")}：${topic.name}`}
      title={`${t("research_graph.open_topic")}：${topic.name}`}
      onClick={() => void onOpen("topic", topic.id)}
    >
      <Badge
        variant={variant}
        className="pointer-events-none transition-shadow group-hover:shadow-md"
      >
        {visibleLabel}
      </Badge>
    </button>
  )
}
