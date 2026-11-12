import styles from "../onboarding.module.css";

export interface BrandMarkProps {
  className?: string;
}

/**
 * The gradient version of the existing FRAME AI mark. The PNG is an alpha mask
 * derived from the original brand asset, so the logo silhouette stays exact
 * while the conic gradient slowly sweeps underneath it.
 */
export function BrandMark({ className }: BrandMarkProps) {
  return (
    <span
      className={`${styles.brandMark}${className ? ` ${className}` : ""}`}
      aria-hidden="true"
    >
      <span className={styles.brandMarkFill} />
    </span>
  );
}
