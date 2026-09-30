import { useEffect, useState } from "react";
import { fetchImageUrl, type ApiConfig } from "../api";

/** A stored image; fetched with the API key, since <img src> can't send headers. */
export function AuthImage({ config, id }: { config: ApiConfig; id: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchImageUrl(config, id)
      .then((url) => {
        objectUrl = url;
        if (cancelled) URL.revokeObjectURL(url);
        else setSrc(url);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [config, id]);

  if (failed) return <div className="thumb thumb-missing">Image unavailable</div>;
  if (!src) return <div className="thumb thumb-loading" aria-label="Loading image" />;
  return <img className="thumb" src={src} alt="Attached image" />;
}
