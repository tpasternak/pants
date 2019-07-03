use futures::Future;
use std::sync::Arc;
use tokio::runtime::Runtime;

#[derive(Clone)]
pub struct Executor {
  runtime: Arc<Runtime>,
}

impl Executor {
  pub fn new() -> Executor {
    Executor {
      runtime: Arc::new(
        Runtime::new().unwrap_or_else(|e| panic!("Could not initialize Runtime: {:?}", e)),
      ),
    }
  }

  ///
  /// Start running a Future on a tokio Runtime.
  ///
  pub fn spawn<F: Future<Item = (), Error = ()> + Send + 'static>(&self, future: F) {
    // Make sure to copy our (thread-local) logging destination into the task.
    // When a daemon thread kicks off a future, it should log like a daemon thread (and similarly
    // for a user-facing thread).
    let logging_destination = crate::get_destination();
    self.runtime.executor().spawn(futures::lazy(move || {
      crate::set_destination(logging_destination);
      future
    }))
  }

  ///
  /// Run a Future on a tokio Runtime as a new Task. This is useful for blocking tokio tasks,
  /// because blocking blocks the entire task called blocking, not just the part of it which is
  /// marked as blocking. This allows finer granularity of marking tasks as blocking.
  ///
  /// See https://docs.rs/tokio-threadpool/0.1.15/tokio_threadpool/fn.blocking.html
  ///
  pub fn spawn_in_new_task<
    Item: Send + 'static,
    Error: Send + 'static,
    F: Future<Item = Item, Error = Error> + Send + 'static,
  >(
    &self,
    future: F,
  ) -> impl Future<Item = Item, Error = Error> {
    // Make sure to copy our (thread-local) logging destination into the task.
    // When a daemon thread kicks off a future, it should log like a daemon thread (and similarly
    // for a user-facing thread).
    let logging_destination = crate::get_destination();
    futures::sync::oneshot::spawn(
      futures::lazy(move || {
        crate::set_destination(logging_destination);
        future
      }),
      &self.runtime.executor(),
    )
  }

  ///
  /// Run a Future and return its resolved Result.
  ///
  /// This should never be called from in a Future context.
  ///
  /// This method makes a new Runtime every time it runs, to ensure that the caller doesn't
  /// accidentally deadlock by using this when a Future attempts to itself call Executor::spawn or
  /// Executor::spawn_in_new_task. Because it should be used only in very limited situations, this
  /// overhead is viewed to be acceptable.
  ///
  pub fn block_on<
    Item: Send + 'static,
    Error: Send + 'static,
    F: Future<Item = Item, Error = Error> + Send + 'static,
  >(
    &self,
    future: F,
  ) -> Result<Item, Error> {
    // Make sure to copy our (thread-local) logging destination into the task.
    // When a daemon thread kicks off a future, it should log like a daemon thread (and similarly
    // for a user-facing thread).
    let logging_destination = crate::get_destination();
    Runtime::new().unwrap().block_on(futures::lazy(move || {
      crate::set_destination(logging_destination);
      future
    }))
  }
}
