use std::cmp::{Ord, Ordering, PartialOrd};

impl PartialOrd<crate::gen::remote_execution::Digest> for crate::gen::remote_execution::Digest {
  fn partial_cmp(&self, other: &crate::gen::remote_execution::Digest) -> Option<Ordering> {
    Some(self.cmp(other))
  }
}

impl Eq for crate::gen::remote_execution::Digest {}

impl Ord for crate::gen::remote_execution::Digest {
  fn cmp(&self, other: &Self) -> Ordering {
    let cmp = self.size_bytes.cmp(&other.size_bytes);
    if Ordering::Equal == cmp {
      self.hash.cmp(&other.hash)
    } else {
      cmp
    }
  }
}
