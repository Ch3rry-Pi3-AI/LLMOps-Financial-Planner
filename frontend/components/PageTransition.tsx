import { useRouter } from "next/router";
import { useEffect, useState, ReactNode } from "react";

/**
 * Props for the PageTransition component.
 *
 * @property {ReactNode} children  
 * The page content to apply transition effects to.
 */
interface PageTransitionProps {
  children: ReactNode;
}

/**
 * PageTransition applies a smooth opacity fade effect whenever the user
 * navigates between routes in the Next.js application.
 *
 * How it works:
 * - Listens to `router.events` for route change start and completion.
 * - When a route begins changing, the wrapper fades to 50% opacity.
 * - Once navigation completes (or errors), opacity returns to 100%.
 *
 * This provides a subtle UI cue to the user that a page transition is occurring,
 * enhancing perceived responsiveness without interfering with interactivity.
 */
export default function PageTransition({ children }: PageTransitionProps) {
  const router = useRouter();

  /**
   * Tracks whether a route transition is in progress.
   * When true → wrapper fades to semi-transparent.
   */
  const [isTransitioning, setIsTransitioning] = useState(false);

  /**
   * Registers event listeners for route change lifecycle events.
   *
   * - routeChangeStart: begin fade-out effect
   * - routeChangeComplete / routeChangeError: fade back in
   *
   * Cleanup removes the listeners if the component unmounts.
   */
  useEffect(() => {
    const handleStart = () => setIsTransitioning(true);
    const handleComplete = () => setIsTransitioning(false);

    router.events.on("routeChangeStart", handleStart);
    router.events.on("routeChangeComplete", handleComplete);
    router.events.on("routeChangeError", handleComplete);

    return () => {
      router.events.off("routeChangeStart", handleStart);
      router.events.off("routeChangeComplete", handleComplete);
      router.events.off("routeChangeError", handleComplete);
    };
  }, [router]);

  return (
    <div
      className={`
        transition-opacity duration-300
        ${isTransitioning ? "opacity-50" : "opacity-100"}
      `}
    >
      {children}
    </div>
  );
}
