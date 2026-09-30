import { useState } from "react";
import { imageUrl } from "../api";

/** A stored image. The session cookie is sent automatically, so a plain <img> works. */
export function StoredImage({ id }: { id: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <div className="thumb thumb-missing">Image unavailable</div>;
  return <img className="thumb" src={imageUrl(id)} alt="Attached image" onError={() => setFailed(true)} />;
}
