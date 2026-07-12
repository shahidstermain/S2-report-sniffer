import type { ComponentType } from "react";

declare module "@/components/ui/card" {
  export const Card: ComponentType<any>;
  export const CardContent: ComponentType<any>;
  export const CardDescription: ComponentType<any>;
  export const CardHeader: ComponentType<any>;
  export const CardTitle: ComponentType<any>;
}

declare module "@/components/ui/badge" {
  export const Badge: ComponentType<any>;
}

declare module "@/components/ui/separator" {
  export const Separator: ComponentType<any>;
}

declare module "../components/NodeDownDetails" {
  const NodeDownDetails: ComponentType<any>;
  export default NodeDownDetails;
}

declare module "../components/ClusterStatePanel" {
  const ClusterStatePanel: ComponentType<any>;
  export default ClusterStatePanel;
}
