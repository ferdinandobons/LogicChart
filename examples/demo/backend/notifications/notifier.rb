module Notifications
  # Routes a message to the requested delivery channel.
  class Notifier
    def deliver(channel, message)
      case channel
      when :email
        send_email(message, urgent?(message))
      when :sms
        send_sms(message)
      when :push
        send_push(message)
      when :inbox
        write_inbox(message)
      else
        queue_for_review(message)
      end
    end

    def digest(channel, messages)
      if messages.empty?
        return queue_for_review("empty digest")
      end
      case channel
      when :email
        send_email(messages.join("\n"), false)
      when :push
        send_push(messages.first)
      else
        queue_for_review(messages.join(","))
      end
    end

    private

    def send_email(message, urgent)
      return message.length + 100 if urgent

      message.length
    end

    def send_sms(message)
      message.length
    end

    def send_push(message)
      message.length
    end

    def write_inbox(message)
      message.length
    end

    def queue_for_review(message)
      message.length
    end

    def urgent?(message)
      message.include?("urgent")
    end
  end
end
