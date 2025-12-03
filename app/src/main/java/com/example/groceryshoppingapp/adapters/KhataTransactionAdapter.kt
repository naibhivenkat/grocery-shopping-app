//package com.example.groceryshoppingapp.adapters
//
//import android.graphics.Color
//import android.view.LayoutInflater
//import android.view.ViewGroup
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.R
//import com.example.groceryshoppingapp.databinding.ItemKhataTransactionBinding
//import com.example.groceryshoppingapp.models.KhataTransaction
//import java.text.SimpleDateFormat
//import java.util.*
//
//class KhataTransactionAdapter(
//    private val transactions: List<KhataTransaction>
//) : RecyclerView.Adapter<KhataTransactionAdapter.ViewHolder>() {
//
//    inner class ViewHolder(val binding: ItemKhataTransactionBinding) :
//        RecyclerView.ViewHolder(binding.root) {
//
//        fun bind(tx: KhataTransaction) {
//
//            // ---- AMOUNT ----
//            val amount = tx.amount ?: 0.0
//            binding.tvAmount.text = "₹${String.format("%.2f", amount)}"
//
//            // -----------------------------
//            //  FIX TIMESTAMP PROPERLY
//            // -----------------------------
//            val createdAt = tx.createdAt  // May be Double or String
//            val createdAtMillis: Long = when (createdAt) {
//
//                // CASE 1 → NEW DATA: epoch seconds as Double
//                is Double -> {
//                    (createdAt * 1000).toLong()
//                }
//
//                // CASE 2 → OLD DATA: ISO STRING like "2025-12-01T23:42:58+05:30"
//                is String -> {
//                    try {
//                        val sdf = SimpleDateFormat(
//                            "yyyy-MM-dd'T'HH:mm:ssXXX",
//                            Locale.getDefault()
//                        )
//                        val date = sdf.parse(createdAt)
//                        date?.time ?: System.currentTimeMillis()
//                    } catch (e: Exception) {
//                        System.currentTimeMillis()
//                    }
//                }
//
//                // CASE 3 → Fallback: extract epoch from tx_id (stable)
//                else -> {
//                    try {
//                        val raw = tx.txId ?: "tx_${System.currentTimeMillis()}"
//                        val id = raw.removePrefix("tx_")
//                        id.toLong()
//                    } catch (e: Exception) {
//                        System.currentTimeMillis()
//                    }
//                }
//
//            }
//
//            val dateStr = SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault())
//                .format(Date(createdAtMillis))
//
//            binding.tvDate.text = dateStr
//
//            // ---- NOTE ----
//            binding.tvNote.text = tx.note ?: ""
//
//            // ---- TYPE ----
//            val type = tx.type ?: ""
//            val typeLower = type.lowercase()
//
//            binding.tvType.text = type.uppercase()
//
//            when (typeLower) {
//                "debit" -> {
//                    binding.tvAmount.setTextColor(Color.parseColor("#F44336"))
//                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_due)
//                }
//                "credit" -> {
//                    binding.tvAmount.setTextColor(Color.parseColor("#4CAF50"))
//                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_clear)
//                }
//                else -> {
//                    binding.tvAmount.setTextColor(Color.parseColor("#000000"))
//                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_clear)
//                }
//            }
//        }
//    }
//
//    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
//        val binding = ItemKhataTransactionBinding.inflate(
//            LayoutInflater.from(parent.context),
//            parent,
//            false
//        )
//        return ViewHolder(binding)
//    }
//
//    override fun getItemCount() = transactions.size
//
//    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
//        holder.bind(transactions[position])
//    }
//}
package com.example.groceryshoppingapp.adapters

import android.graphics.Color
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.databinding.ItemKhataTransactionBinding
import com.example.groceryshoppingapp.models.KhataTransaction
import java.text.SimpleDateFormat
import java.util.*

class KhataTransactionAdapter(
    private val transactions: List<KhataTransaction>
) : RecyclerView.Adapter<KhataTransactionAdapter.ViewHolder>() {

    inner class ViewHolder(val binding: ItemKhataTransactionBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(tx: KhataTransaction) {

            // --- AMOUNT ---
            val amount = tx.amount ?: 0.0
            binding.tvAmount.text = "₹${String.format("%.2f", amount)}"

            // --- TIMESTAMP FIX: createdAt is ALWAYS STRING now ---
            val epochMillis = try {
                tx.createdAt?.toLong() ?: System.currentTimeMillis()
            } catch (e: Exception) {
                System.currentTimeMillis()
            }

            val sdf = SimpleDateFormat("dd MMM yyyy, hh:mm a", Locale.getDefault())
            sdf.timeZone = TimeZone.getTimeZone("Asia/Kolkata")

            binding.tvDate.text = sdf.format(Date(epochMillis))

            // --- NOTE ---
            binding.tvNote.text = tx.note ?: ""

            // --- TYPE ---
            val typeLower = tx.type?.lowercase() ?: ""
            binding.tvType.text = typeLower.uppercase()

            when (typeLower) {
                "debit" -> {
                    binding.tvAmount.setTextColor(Color.parseColor("#F44336"))
                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_due)
                }
                "credit" -> {
                    binding.tvAmount.setTextColor(Color.parseColor("#4CAF50"))
                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
                else -> {
                    binding.tvAmount.setTextColor(Color.BLACK)
                    binding.tvType.setBackgroundResource(R.drawable.bg_khata_badge_clear)
                }
            }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemKhataTransactionBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return ViewHolder(binding)
    }

    override fun getItemCount() = transactions.size

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        holder.bind(transactions[position])
    }
}
