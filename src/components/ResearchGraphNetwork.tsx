import { useEffect, useRef } from "react"
import { DataSet } from "vis-data"
import { Network } from "vis-network"
import type { ResearchGraph, ResearchGraphObjectType } from "@/types"

const GROUP_COLORS = {
  author: "#2563eb",
  collaborator: "#0f766e",
  paper: "#7c3aed",
  topic: "#d97706",
  institution: "#475569",
}

export default function ResearchGraphNetwork({
  graph,
  onObjectClick,
}: {
  graph: ResearchGraph["local_network"]
  onObjectClick: (objectType: ResearchGraphObjectType, objectId: string) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!containerRef.current || !graph.nodes.length) return
    const nodes = new DataSet(graph.nodes.map((node) => ({
      id: node.id,
      label: node.label.length > 38 ? `${node.label.slice(0, 36)}…` : node.label,
      title: node.label,
      shape: node.group === "paper" ? "box" : node.group === "topic" ? "ellipse" : "dot",
      size: node.group === "author" ? 28 : node.group === "collaborator" ? 19 : 15,
      color: {
        background: GROUP_COLORS[node.group],
        border: GROUP_COLORS[node.group],
        highlight: { background: GROUP_COLORS[node.group], border: "#0f172a" },
      },
      font: {
        color: node.group === "paper" ? "#f8fafc" : "#334155",
        size: node.group === "author" ? 15 : 12,
      },
    })))
    const edges = new DataSet(graph.edges.map((edge, index) => ({
      id: `${edge.from}:${edge.to}:${index}`,
      from: edge.from,
      to: edge.to,
      label: edge.label,
      arrows: { to: edge.type === "authored" || edge.type === "has_topic" },
      color: { color: "rgba(100, 116, 139, 0.45)", highlight: "#2563eb" },
      font: { size: 10, color: "#64748b", strokeWidth: 3 },
      width: edge.type === "collaborates" ? 2 : 1,
    })))
    const network = new Network(containerRef.current, { nodes, edges }, {
      autoResize: true,
      interaction: {
        dragNodes: true,
        dragView: true,
        hover: true,
        navigationButtons: true,
        zoomSpeed: 0.15,
      },
      physics: {
        stabilization: { enabled: true, iterations: 160 },
        barnesHut: {
          gravitationalConstant: -3000,
          centralGravity: 0.2,
          springLength: 130,
          springConstant: 0.035,
        },
      },
      edges: { smooth: { enabled: true, type: "dynamic", roundness: 0.5 } },
    })
    network.on("click", (params: { nodes: string[] }) => {
      const nodeId = params.nodes[0]
      const node = graph.nodes.find((item) => item.id === nodeId)
      if (node) onObjectClick(node.object_type, node.object_id)
    })
    return () => network.destroy()
  }, [graph, onObjectClick])

  if (!graph.nodes.length) return null
  return <div ref={containerRef} className="h-[28rem] rounded-lg border bg-card" />
}
